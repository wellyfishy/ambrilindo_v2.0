from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter(name='is_kumite_beregu')
def is_kumite_beregu(detail_bagan):
    if not detail_bagan or not detail_bagan.bagan:
        return False
    bagan = detail_bagan.bagan
    is_kumite = (bagan.tipe_tanding == '2') or ('kumite' in (bagan.nama_bagan or '').lower())
    if not is_kumite:
        return False
    nt_name = bagan.nomor_tanding.nama_nomor_tanding.lower() if bagan.nomor_tanding and bagan.nomor_tanding.nama_nomor_tanding else ''
    bagan_name = (bagan.nama_bagan or '').lower()
    is_beregu = ('beregu' in nt_name) or ('beregu' in bagan_name) or ('team' in bagan_name)
    return is_beregu and not getattr(detail_bagan, 'team', False)

@register.filter(name='is_kata_beregu')
def is_kata_beregu(detail_bagan):
    if not detail_bagan or not detail_bagan.bagan:
        return False
    bagan = detail_bagan.bagan
    is_kata = (bagan.tipe_tanding == '1') or ('kata' in (bagan.nama_bagan or '').lower())
    if not is_kata:
        return False
    nt_name = bagan.nomor_tanding.nama_nomor_tanding.lower() if bagan.nomor_tanding and bagan.nomor_tanding.nama_nomor_tanding else ''
    bagan_name = (bagan.nama_bagan or '').lower()
    return ('beregu' in nt_name) or ('beregu' in bagan_name) or ('team' in bagan_name)

@register.filter(name='contains_team')
def contains_team(detail_bagan):
    # Only return True for Kumite Beregu so Kata Beregu always uses standard control panel
    return is_kumite_beregu(detail_bagan)