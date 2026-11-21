"""Deterministic rendering; no prose can be added outside structured fields."""
def derived_status(claims, missing_information):
    return ('PARTIAL' if missing_information else 'ANSWERED') if claims else 'INSUFFICIENT_SOURCES'


def render_body(claims, missing_information):
    lines=[claim['text']+' '+''.join('['+sid+']' for sid in claim['source_ids']) for claim in claims]
    lines.extend('Missing information: '+item for item in missing_information)
    return '\n'.join(lines)


def render_sources(sources):
    lines=[]
    for source in sources:
        citation=source['citation']
        lines.append('Source ['+source['source_id']+']: '+citation['title']+' | '+citation['published_at_utc'])
        lines.append(citation['url'])
    return '\n'.join(lines)
