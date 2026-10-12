"""Read-only Excel value reader used by Home Accounts imports."""
import io, re, zipfile
import xml.etree.ElementTree as ET
NS = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def read_xlsx(data):
    """Read values/cached formula results, preserving sparse column positions."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(x.file_size for x in z.infolist()) > 50_000_000: raise ValueError('Workbook is too large.')
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(s.itertext()) for s in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        result={}
        date1904 = ET.fromstring(z.read('xl/workbook.xml')).find('m:workbookPr', NS)
        if date1904 is not None and date1904.attrib.get('date1904') in ('1', 'true'):
            raise ValueError('1904-date workbooks are not supported. Export dates as ISO CSV instead.')
        for s in ET.fromstring(z.read('xl/workbook.xml')).find('m:sheets',NS):
            target=rels[s.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            path=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            rows=[]
            for row in ET.fromstring(z.read(path)).findall('.//m:sheetData/m:row',NS):
                n=int(row.attrib['r'])
                while len(rows)<n: rows.append([])
                cells=[]
                for c in row:
                    col=0
                    for ch in re.match(r'[A-Z]+',c.attrib['r'])[0]: col=col*26+ord(ch)-64
                    while len(cells)<col: cells.append('')
                    v=c.find('m:v',NS)
                    value=v.text if v is not None and v.text is not None else ''
                    if c.attrib.get('t')=='s': value=strings[int(value)] if value else ''
                    elif c.attrib.get('t')=='inlineStr': value=''.join(c.find('m:is',NS).itertext())
                    cells[col-1]=value
                rows[n-1]=cells
            result[s.attrib['name']]=rows
        return result
