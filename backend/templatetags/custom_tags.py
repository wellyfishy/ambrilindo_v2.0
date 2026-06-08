from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter(name='contains_team')
def contains_team(detail_bagan):
    # Check if atlet1 exists AND contains 'team'
    check_aka = (detail_bagan.atlet1 is not None and 
                 'team' in detail_bagan.atlet1.nama_atlet.lower())
    
    # Check if atlet2 exists AND contains 'team'
    check_ao = (detail_bagan.atlet2 is not None and 
                'team' in detail_bagan.atlet2.nama_atlet.lower())
    
    return check_aka or check_ao