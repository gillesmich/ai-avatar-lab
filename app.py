import csv, sys, re

GBK = '/workspace/IB_AAP_BAK/sauvegarde_appels_offre.gbk'
OUT = '/workspace/IB_AAP_BAK/PHRCREGIONNAL2012.csv'
BLOC_OFF = 12969876
BLOC_LEN = 16719

COLS = [
    'CODE_PROJET','NOM','PRENOM','EMAIL','ACTIF',
    'COL_BIN','CIVILITE','COMMENTAIRE','ANCIEN_CODE_RAPP2',
    'DATE_ENVOI_LISTE_RAPP1','DATE_ENVOI_LISTE_RAPP2',
    'DATE_ENVOI_POINT_RAPP1','DATE_ENVOI_POINT_RAPP2',
    'DATE_ENVOI_LI_RAPP1','DATE_ENVOI_LI_RAPP2',
    'DATE_ENVOI_LI_LISTE_RAPP1','DATE_ENVOI_LI_LISTE_RAPP2',
    'DATE_RETOUR_LI_RAPP1','DATE_RETOUR_LI_RAPP2',
    'NOTE_LI_RAPP1','NOTE_LI_RAPP2',
    'DATE_ENVOI_LI1_RAPP1','DATE_ENVOI_LI1_RAPP2',
    'DATE_RETOUR_LI1_RAPP1','DATE_RETOUR_LI1_RAPP2',
    'NOTE_LI1_RAPP1','NOTE_LI1_RAPP2',
    'DATE_ENVOI_ITEM_RAPP1','DATE_ENVOI_ITEM_RAPP2',
    'SOUS_NOTE1_LI_RAPP1','SOUS_NOTE1_LI_RAPP2',
    'SOUS_NOTE2_LI_RAPP1','SOUS_NOTE2_LI_RAPP2',
]

def parse_record(rec_bytes):
    """Parse les champs XDR d'un enregistrement gbak brut."""
    fields = []
    i = 0
    while i < len(rec_bytes) - 2:
        m = rec_bytes[i]
        # Format: marker(1) + len_total(1) + len_data(1) + data
        if m >= 0xdd and i+2 < len(rec_bytes):
            ltot = rec_bytes[i+1]
            ldat = rec_bytes[i+2] if i+2 < len(rec_bytes) else 0
            # Cas NULL
            if ltot == 0:
                fields.append(None)
                i += 2
                continue
            # Cas avec 2 octets de longueur (ltot + ldat)
            if ldat <= ltot and i+3+ldat <= len(rec_bytes):
                val = rec_bytes[i+3:i+3+ldat].decode('latin-1').strip('\x00 \t\r\n')
                fields.append(val)
                i += 3 + ldat
                continue
        # Format court: marker(1) + len(1) + data  (sans octet ldat séparé)
        if m >= 0xdd and i+1 < len(rec_bytes):
            ldat = rec_bytes[i+1]
            if 0 < ldat <= 200 and i+2+ldat <= len(rec_bytes):
                val = rec_bytes[i+2:i+2+ldat].decode('latin-1').strip('\x00 \t\r\n')
                fields.append(val)
                i += 2 + ldat
                continue
        i += 1
    return fields

def clean(v):
    if v is None:
        return ''
    return ''.join(c for c in v if ord(c) >= 0x20 and ord(c) != 0x7f).strip()

def main():
    with open(GBK, 'rb') as f:
        f.seek(BLOC_OFF + 3)
        bloc = f.read(BLOC_LEN)

    print(f"[INFO] Bloc: {len(bloc)} bytes", file=sys.stderr)
    print(f"[INFO] Debut hex: {bloc[:20].hex()}", file=sys.stderr)

    # Le byte 0x52 ('R') est le séparateur de record dans le format gbak
    # Debut du bloc: 52 fd 31 04 33 37 20 20 ...
    # 0x52 = debut record, suivi directement des champs XDR
    rec_starts = [i for i in range(len(bloc)) if bloc[i] == 0x52]
    print(f"[INFO] Occurrences 0x52: {len(rec_starts)}", file=sys.stderr)
    print(f"[INFO] 20 premieres positions: {rec_starts[:20]}", file=sys.stderr)

    # Verifie que le 1er byte est bien 0x52
    # et que juste apres on a un champ commencant par un marker >= 0xdd ou 0xfd
    valid_starts = []
    for pos in rec_starts:
        if pos + 1 < len(bloc):
            next_b = bloc[pos+1]
            if next_b >= 0xdd or next_b == 0xfd:
                valid_starts.append(pos)

    print(f"[INFO] Starts valides (0x52 + marker): {len(valid_starts)}", file=sys.stderr)
    print(f"[INFO] Positions: {valid_starts[:20]}", file=sys.stderr)

    # Extrait chaque enregistrement
    records_raw = []
    for idx, start in enumerate(valid_starts):
        end = valid_starts[idx+1] if idx+1 < len(valid_starts) else len(bloc)
        rec_bytes = bloc[start+1:end]  # saute le 0x52
        records_raw.append(rec_bytes)

    print(f"[INFO] Records bruts: {len(records_raw)}", file=sys.stderr)

    # Parse chaque record
    records = []
    for rb in records_raw:
        fields = parse_record(rb)
        records.append([clean(f) for f in fields])

    print(f"\n[SAMPLE] 5 premiers records:", file=sys.stderr)
    for r in records[:5]:
        print(f"  {r[:6]}", file=sys.stderr)

    if not records:
        print("[ERREUR] Aucun record", file=sys.stderr)
        sys.exit(1)

    maxf = max(len(r) for r in records)
    hdr = COLS[:min(len(COLS), maxf)] + [f'COL_{i}' for i in range(len(COLS), maxf)]

    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(hdr)
        for rec in records:
            row = rec + [''] * max(0, len(hdr) - len(rec))
            w.writerow(row[:len(hdr)])

    print(f"\n[OK] {OUT} — {len(records)} lignes", file=sys.stderr)

if __name__ == '__main__':
    main()
