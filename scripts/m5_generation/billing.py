"""Auditable usage-based estimates. Missing usage or prices never becomes zero cost."""
from decimal import Decimal, InvalidOperation
from copy import deepcopy
from datetime import datetime
from .api import M5Error

FIELDS={'schema_version','model','currency','input_cache_hit_per_million','input_cache_miss_per_million',
        'output_per_million','source_url','verified_at_utc'}


def validate_pricing(value,model):
    if not isinstance(value,dict) or set(value)!=FIELDS or value['schema_version']!='m5_pricing.v1':
        raise M5Error('INVALID_PRICING','Use the documented pricing fields.')
    if value['model']!=model or value['currency'] not in ('USD','CNY'):
        raise M5Error('INVALID_PRICING','Pricing model or currency does not match.')
    if not isinstance(value['source_url'],str) or not value['source_url'].startswith('https://'):
        raise M5Error('INVALID_PRICING','Provide a traceable HTTPS pricing source.')
    if not isinstance(value['verified_at_utc'],str) or not value['verified_at_utc'].endswith('Z'):
        raise M5Error('INVALID_PRICING','Record the UTC time at which the pricing was verified.')
    try:
        datetime.fromisoformat(value['verified_at_utc'].replace('Z','+00:00'))
    except ValueError:
        raise M5Error('INVALID_PRICING','Pricing verification time must be a valid UTC timestamp.') from None
    for field in ('input_cache_hit_per_million','input_cache_miss_per_million','output_per_million'):
        try:
            number=Decimal(str(value[field]))
            if isinstance(value[field],bool) or not number.is_finite() or number<0 or number>1000000:raise ValueError()
        except (InvalidOperation,ValueError,TypeError):
            raise M5Error('INVALID_PRICING','Rates must be finite nonnegative amounts per million tokens.') from None
    return value


def summarize_calls(calls,pricing,model):
    result={'method':'provider_usage_times_configured_rates','currency':pricing.get('currency') if pricing else None,
            'pricing_snapshot':deepcopy(pricing),'pricing_valid':False,'complete':False,'total_cost':None,
            'known_response_cost':None,'missing_or_unknown_calls':[],'per_request':[],
            'not_an_invoice':True,'scope':'All physical requests, including generation, review, repair and retries.'}
    if pricing is not None:
        try:
            validate_pricing(pricing,model)
            result['pricing_valid']=True
        except M5Error:
            result['reason']='invalid_pricing'
            return result
    if not calls:
        result.update(complete=True,total_cost='0',known_response_cost='0',reason='no_api_requests')
        return result
    if pricing is None:
        result.update(reason='pricing_not_configured',missing_or_unknown_calls=list(range(1,len(calls)+1)))
        return result
    total=Decimal(0)
    for i,call in enumerate(calls,1):
        cost=None;reason=None
        prompt,completion=call.get('input_tokens'),call.get('output_tokens')
        hit,miss=call.get('cache_hit_tokens'),call.get('cache_miss_tokens')
        numbers=lambda *vals:all(type(v) is int and v>=0 for v in vals)
        if call.get('state')!='RECEIVED' or not numbers(prompt,completion):
            reason='missing_usage_or_unknown_provider_outcome'
        elif call.get('requested_model')!=model or call.get('returned_model')!=model:
            reason='model_not_covered_by_pricing'
        else:
            a,b,c=(Decimal(str(pricing[k])) for k in ('input_cache_hit_per_million','input_cache_miss_per_million','output_per_million'))
            if not numbers(hit,miss) or hit+miss!=prompt:
                if a==b:hit,miss=0,prompt
                else:reason='cache_usage_missing_or_inconsistent'
            if reason is None:
                cost=(a*hit+b*miss+c*completion)/Decimal(1000000)
                total+=cost
        result['per_request'].append({'request':i,'cost':str(cost) if cost is not None else None,'reason':reason})
        if cost is None:result['missing_or_unknown_calls'].append(i)
    result['known_response_cost']=str(total)
    result['complete']=not result['missing_or_unknown_calls']
    result['total_cost']=str(total) if result['complete'] else None
    result['reason']='estimated_from_recorded_usage' if result['complete'] else 'incomplete_do_not_treat_subtotal_as_total'
    return result
