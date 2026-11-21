"""Bounded transport retries, distinct from content repair; every dispatch is logged."""
import time
from .api import M5Error
from .token_budget import check_budget, observe_usage

RETRYABLE={'HTTP_429','HTTP_502','HTTP_503','HTTP_504','NETWORK_ERROR','API_TIMEOUT'}


def request_with_retry(payload,key,*,api_call,ledger,stage,logical_call,max_requests,retries,emit,sleep=time.sleep):
    budget=check_budget(payload)
    for index in range(retries+1):
        if len(ledger)>=max_requests:
            raise M5Error('CALL_LIMIT','The physical API request limit was reached.')
        call={'stage':stage,'attempt':len(ledger)+1,'logical_call':logical_call,'network_attempt':index+1,
              'state':'STARTING','input_tokens':None,'output_tokens':None,'cache_hit_tokens':None,'cache_miss_tokens':None,
              'requested_model':payload['model'],'returned_model':None,'latency_ms':None,'error_code':None,
              'token_budget':budget,'retry_scheduled':False,'billing_outcome_unknown':True}
        ledger.append(call)
        emit()  # Save intent before sending; interrupted intent is not evidence of zero cost.
        started=time.perf_counter()
        try:
            response=api_call(payload,key)
            call['state']='RECEIVED'
            if isinstance(response,dict):
                call['returned_model']=response.get('model')
                usage=response.get('usage')
                if isinstance(usage,dict):
                    for field,remote in (('input_tokens','prompt_tokens'),('output_tokens','completion_tokens'),
                                         ('cache_hit_tokens','prompt_cache_hit_tokens'),('cache_miss_tokens','prompt_cache_miss_tokens')):
                        value=usage.get(remote)
                        if type(value) is int and value>=0:call[field]=value
            call['billing_outcome_unknown']=call['input_tokens'] is None or call['output_tokens'] is None
            call['token_budget']=observe_usage(budget,call['input_tokens'])
            return response
        except M5Error as exc:
            call.update(state='FAILED',error_code=exc.code)
            if index==retries or exc.code not in RETRYABLE:raise
            call.update(retry_scheduled=True,retry_delay_seconds=1)
        except KeyboardInterrupt:
            call['state']='INTERRUPTED_OUTCOME_UNKNOWN'
            raise
        except Exception:
            call.update(state='FAILED',error_code='UNEXPECTED_TRANSPORT_ERROR')
            raise M5Error('UNEXPECTED_TRANSPORT_ERROR','The API transport failed; no response or exception body was logged.') from None
        finally:
            call['latency_ms']=round((time.perf_counter()-started)*1000,2)
            emit()
        sleep(1)
