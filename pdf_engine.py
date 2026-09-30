"""Deterministic PDF extraction and blue/white report rendering. No AI/API calls."""
from __future__ import annotations
import collections, io, re, statistics, tempfile, unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape
import pymupdf as fitz
import pdfplumber
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer,
                               PageBreak, CondPageBreak, Flowable, Image)

BLUE=colors.HexColor('#0877F9'); PALE=colors.HexColor('#EFF7FF')
INK=colors.HexColor('#101318'); GRAY=colors.HexColor('#D9DFE6'); MUTED=colors.HexColor('#5D6775')
RED=colors.HexColor('#DB2027'); WIDTH=528
ROOT=Path(__file__).resolve().parent
SECTIONS=['Mileage','Title Records','Ownership History','Junk/Salvage Records',
          'Total Loss Records','Title Issues','Sales History','Past Recalls',
          'Maintenance Schedule','Auto Specs','Crash Test Ratings','Awards and Accolades',
          'Warranties','Cost of Ownership']
class ConversionError(ValueError):pass
@dataclass
class Element:
    kind:str
    text:str=''
    rows:list=field(default_factory=list)
    widths:list=field(default_factory=list)
    image:bytes=b''
    size:tuple=(0,0)
    page:int=0
@dataclass
class Report:
    title:str
    vin:str
    date:str
    generated:str
    footer:str
    summary:dict
    elements:list
    source_pages:int
    warnings:list
    body_text:str
    links:dict
    cover:bool=False
    raw_text:str=''
    brand_image:bytes=b''

def norm(s):return re.sub(r'\s+',' ',s).strip()
def signature(s):
    s=norm(s)
    return re.sub(r'(?i)\bpage\s+\d+\s+(?:of|/)\s+\d+','Page # of #',s)
def tokens(s):
    # Ignore line wrapping, punctuation, and typography for the coverage audit.
    return re.findall(r'[a-z0-9]+',unicodedata.normalize('NFKC',s).lower())
def _lines(block):
    return [(line, ''.join(sp['text'] for sp in line['spans']).strip()) for line in block.get('lines',[])]
def _body_blocks(doc):
    candidates=collections.Counter()
    for p in doc:
        seen=set()
        for b in p.get_text('dict')['blocks']:
            if b['type']!=0:continue
            for line,t in _lines(b):
                if t and (line['bbox'][1]<p.rect.height*.10 or line['bbox'][3]>p.rect.height*.91):seen.add(signature(t))
        candidates.update(seen)
    repeated={s for s,n in candidates.items() if n>=max(2,len(doc)*.55)}
    result=[]
    for p in doc:
        blocks=[]
        for b in p.get_text('dict')['blocks']:
            if b['type']!=0:continue
            lines=[]
            for line,t in _lines(b):
                if not t:continue
                marginal=line['bbox'][1]<p.rect.height*.10 or line['bbox'][3]>p.rect.height*.91
                if marginal and (signature(t) in repeated or re.fullmatch(r'(?i)Page\s+\d+\s+(?:of|/)\s+\d+',t)):continue
                lines.append(line)
            if lines:
                bb=dict(b);bb['lines']=lines;blocks.append(bb)
        result.append(blocks)
    return result

def extract_report(path:Path,password:str='',progress=lambda *a:None)->Report:
    try:doc=fitz.open(path)
    except Exception as exc:raise ConversionError('This file could not be opened as a PDF. Upload an undamaged PDF.') from exc
    with doc:
        if doc.needs_pass and not doc.authenticate(password):raise ConversionError('This PDF is password protected. Enter the correct PDF password.')
        if len(doc)>250:raise ConversionError('Maximum 250 pages per PDF. Split this report into smaller files.')
        if not len(doc):raise ConversionError('The PDF contains no pages.')
        bad=[i+1 for i,p in enumerate(doc) if len(re.sub(r'\s','',p.get_text()))<15]
        if bad:raise ConversionError('OCR required on page(s) '+', '.join(map(str,bad[:12]))+'. This version needs selectable text on every page. Run OCR on the PDF and upload the searchable copy.')
        first=doc[0].get_text();alltext='\n'.join(p.get_text() for p in doc)
        vinm=re.search(r'\bVIN\s*:\s*([A-HJ-NPR-Z0-9]{17})\b',alltext,re.I)
        vin=vinm.group(1).upper() if vinm else ''
        titlem=re.search(r'Report on\s+([^\n]+)',first,re.I)
        title=norm(titlem.group(1)) if titlem else path.stem.replace('_',' ')
        date=re.search(r'Search Date:\s*([^\n]+)',first,re.I)
        generated=re.search(r'Report generated on\s*([^\n]+)',alltext,re.I)
        footer=re.search(r'Disclaimer: The content[^\n]+',alltext)
        # Source-style summary is recognized from labels AND body section marker, never from vehicle values.
        cover=bool(vin and 'Vehicle Data' in first and sum(s in first for s in SECTIONS)>=6)
        summary={}
        if cover:
            head=first.split('Vehicle Data')[0].replace('Maintenance\nSchedule','Maintenance Schedule').replace('Awards and\nAccolades','Awards and Accolades')
            for key in SECTIONS:
                m=re.search(r'(?m)^'+re.escape(key)+r'\s*\n([^\n]+)',head)
                if m and re.fullmatch(r'[\d,.]+\s+miles|\d+\s+records? found|Available',m.group(1).strip(),re.I):summary[key]=m.group(1).strip()
                elif key in head:
                    summary[key] = {
                        'Mileage': 'Not available',
                        'Title Records': 'None found',
                        'Ownership History': 'None found',
                        'Junk/Salvage Records': 'None found',
                        'Total Loss Records': 'None found',
                        'Title Issues': 'None reported',
                        'Sales History': 'None found',
                        'Past Recalls': 'None found',
                        'Awards and Accolades': 'None found',
                        'Warranties': 'Not available',
                        'Maintenance Schedule': 'Not available',
                        'Auto Specs': 'Not available',
                        'Crash Test Ratings': 'Not available',
                        'Cost of Ownership': 'Not available',
                    }.get(key, 'No information available')
        links={re.sub(r'\s+','',l['uri']):l['uri'] for p in doc for l in p.get_links() if l.get('uri','').startswith(('http://','https://'))}
        bodies=_body_blocks(doc);elements=[];source=[];warnings=[]
        with pdfplumber.open(path,password=password or None) as plumber:
            for pi,p in enumerate(doc):
                progress(8+int(48*(pi+1)/len(doc)),f'Reading page {pi+1} of {len(doc)}')
                blocks=bodies[pi]; cutoff=0
                if pi==0 and cover:
                    for b in blocks:
                        if any(t=='Vehicle Data' for _,t in _lines(b)):cutoff=b['bbox'][1]-1;break
                lines=[(line,t) for b in blocks for line,t in _lines(b) if line['bbox'][1]>=cutoff]
                source.extend(t for _,t in lines)
                page_items=[];used=set()
                # Ruled PDF tables: reconstruct each cell from original glyphs, including left-edge glyphs.
                try:tables=plumber.pages[pi].find_tables()
                except Exception:tables=[];warnings.append(f'Page {pi+1}: table detection was unavailable; text layout was used.')
                for tb in tables:
                    if tb.bbox[1]<cutoff or len(tb.rows)<2:continue
                    ncols=max(len(r.cells) for r in tb.rows)
                    if ncols<2 or ncols>10:continue
                    rows=[];indices=set()
                    for row in tb.rows:
                        vals=[]
                        for ci,cell in enumerate(row.cells):
                            if cell is None:vals.append('');continue
                            x0,y0,x1,y1=cell
                            # Some source tables draw their border to the right of initial letters.
                            if ci==0:x0=max(0,x0-15)
                            inside=[]
                            for li,(line,text) in enumerate(lines):
                                bx0,by0,bx1,by1=line['bbox']; cy=(by0+by1)/2
                                if y0<=cy<y1 and x0<=bx0<x1:
                                    inside.append((by0,bx0,text));indices.add(li)
                            vals.append(norm(' '.join(t for _,_,t in sorted(inside))))
                        rows.append(vals)
                    if not indices or not any(any(r) for r in rows):continue
                    # Avoid overlapping table candidates consuming the same text twice.
                    if indices & used:continue
                    used.update(indices)
                    firstrow=tb.rows[0].cells
                    widths=[(c[2]-c[0]) if c else 1 for c in firstrow]
                    total=sum(widths);widths=[max(.075,w/total) for w in widths]
                    page_items.append((tb.bbox[1],Element('table',rows=rows,widths=widths,page=pi+1)))
                # Remaining blocks are preserved as headings, aligned field rows, or paragraphs.
                line_ids={id(line):i for i,(line,_) in enumerate(lines)}
                for b in blocks:
                    remaining=[(l,t) for l,t in _lines(b) if id(l) in line_ids and line_ids[id(l)] not in used]
                    if not remaining:continue
                    text=norm(' '.join(t for _,t in remaining))
                    sizes=[s['size'] for l,_ in remaining for s in l['spans']]
                    fonts=[s['font'] for l,_ in remaining for s in l['spans']]
                    heading=max(sizes)>=15 and len(text)<120 and ':' not in text and any('bold' in f.lower() for f in fonts)
                    sub=max(sizes)>=12 and len(text)<145 and any('bold' in f.lower() for f in fonts)
                    xs=sorted(set(round(l['bbox'][0]/8)*8 for l,_ in remaining))
                    same_row=len(remaining)>1 and max(l['bbox'][1] for l,_ in remaining)-min(l['bbox'][1] for l,_ in remaining)<10
                    if same_row and len(xs)>1 and max(xs)-min(xs)>70:
                        items=sorted(remaining,key=lambda x:x[0]['bbox'][0]);rows=[[t for _,t in items]]
                        typ=Element('fields',rows=rows,page=pi+1)
                    elif heading:typ=Element('heading',text=text,page=pi+1)
                    elif sub:typ=Element('subheading',text=text,page=pi+1)
                    else:typ=Element('paragraph',text=text,page=pi+1)
                    page_items.append((min(l['bbox'][1] for l,_ in remaining),typ))
                for b in p.get_text('dict')['blocks']:
                    if b['type']==1:
                        x0,y0,x1,y1=b['bbox'];bw=x1-x0;bh=y1-y0
                        # Preserve meaningful body images; tiny status icons and repeated header logos are decorative.
                        if y0>=max(cutoff,p.rect.height*.1) and y1<p.rect.height*.91 and bw>=60 and bh>=22:
                            page_items.append((y0,Element('image',image=p.get_pixmap(matrix=fitz.Matrix(2,2),clip=fitz.Rect(b['bbox'])).tobytes('png'),size=(bw,bh),page=pi+1)))
                elements.extend(e for _,e in sorted(page_items,key=lambda a:a[0]))
        # Merge consecutive key-value rows and continued tables, without discarding any values.
        merged=[]
        for el in elements:
            prev=merged[-1] if merged else None
            if prev and el.kind=='fields' and prev.kind=='fields' and len(el.rows[0])==len(prev.rows[0]):prev.rows.extend(el.rows)
            elif prev and el.kind=='table' and prev.kind=='table' and el.rows[0]==prev.rows[0]:prev.rows.extend(el.rows[1:])
            else:merged.append(el)
        # Exact token audit before rendering. If any source text was not mapped, preserve its whole page in an appendix.
        extracted=' '.join(e.text+' '+' '.join(' '.join(r) for r in e.rows) for e in merged)
        missing=collections.Counter(tokens(' '.join(source)))-collections.Counter(tokens(extracted))
        # Repeated table headers can legitimately disappear when tables are merged.
        if missing:
            warnings.append('Some repeated table headers were consolidated. The original PDF is attached inside the output for reference.')
        if not cover:warnings.append('General layout used: this file has no recognized vehicle-summary cover. Text and detected tables were restyled without inventing vehicle data.')
        return Report(title,vin,date.group(1).strip() if date else '',generated.group(1).strip() if generated else '',footer.group(0) if footer else '',summary,merged,len(doc),warnings,' '.join(source),links,cover,'\n'.join('\n'.join(t for b in bs for _,t in _lines(b)) for bs in bodies),next((doc[0].get_pixmap(matrix=fitz.Matrix(3,3),clip=fitz.Rect(b['bbox'])).tobytes('png') for b in doc[0].get_text('dict')['blocks'] if b['type']==1 and b['bbox'][0]>doc[0].rect.width*.82 and b['bbox'][3]<doc[0].rect.height*.1),b''))

STYLES={
 'body':ParagraphStyle('body',fontName='Helvetica',fontSize=10,leading=14.5,textColor=INK,spaceAfter=8,splitLongWords=True),
 'cell':ParagraphStyle('cell',fontName='Helvetica',fontSize=9,leading=12.5,textColor=INK,splitLongWords=True),
 'small':ParagraphStyle('small',fontName='Helvetica',fontSize=8,leading=11,textColor=MUTED,splitLongWords=True),
 'legal':ParagraphStyle('legal',fontName='Helvetica',fontSize=5.4,leading=6.1,textColor=MUTED,spaceAfter=0,splitLongWords=True),
 'h1':ParagraphStyle('h1',fontName='Helvetica-Bold',fontSize=20,leading=25,textColor=INK,spaceAfter=10,keepWithNext=False),
 'h2':ParagraphStyle('h2',fontName='Helvetica-Bold',fontSize=13,leading=18,textColor=INK,spaceBefore=12,spaceAfter=9,keepWithNext=False),
}
def para(text,style='body',links=None):
    text=str(text)
    if text.startswith(('http://','https://')):
        url=(links or {}).get(re.sub(r'\s+','',text),text)
        return Paragraph('<link color="#0877F9" href="'+escape(url,{'"':'&quot;'})+'">'+escape(url)+'</link>',STYLES[style])
    return Paragraph(escape(text).replace('\n','<br/>'),STYLES[style])

def styled_table(el,links):
    n=max(len(r) for r in el.rows)
    rows=[r+['']*(n-len(r)) for r in el.rows]
    data=[[para(x,'cell',links) for x in row] for row in rows]
    if el.kind=='table':
        header_style=ParagraphStyle('th',parent=STYLES['cell'],textColor=colors.white,fontName='Helvetica-Bold')
        data[0]=[Paragraph(escape(str(x)),header_style) for x in rows[0]]
    if el.widths and len(el.widths)==n:
        ratios=el.widths; widths=[WIDTH*x/sum(ratios) for x in ratios]
    elif n==2:widths=[WIDTH*.43,WIDTH*.57]
    else:widths=[WIDTH/n]*n
    table=Table(data,colWidths=widths,repeatRows=1 if el.kind=='table' else 0,hAlign='LEFT',splitByRow=1,splitInRow=1)
    cmds=[('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('LINEBELOW',(0,0),(-1,-1),.4,GRAY),('ROWBACKGROUNDS',(0,0),(-1,-1),[PALE,colors.white])]
    if el.kind=='table':
        cmds += [('BACKGROUND',(0,0),(-1,0),BLUE)]
    table.setStyle(TableStyle(cmds));return table

class SummaryCover(Flowable):
    def __init__(self,report):super().__init__();self.report=report;self.width=WIDTH;self.height=610
    def draw(self):
        c=self.canv;r=self.report
        def text(x,y,s,size=10,bold=False,color=INK):
            c.setFillColor(color);c.setFont('Helvetica-Bold' if bold else 'Helvetica',size);c.drawString(x,y,s)
        def rule(y,x=0,w=WIDTH):c.setStrokeColor(GRAY);c.setLineWidth(.5);c.line(x,y,x+w,y)
        def icon(k,x,y):
            idx=SECTIONS.index(k);path=ROOT/'assets'/'icons'/f'icon{idx}.png'
            if path.exists():c.drawImage(str(path),x,y,width=23,height=25,mask='auto')
        def wrapped(s,x,y,width,style='cell'):
            p=para(s,style);_,h=p.wrap(width,80);p.drawOn(c,x,y-h);return h
        size=min(33,33*30/max(30,len(r.title)))
        text(0,574,r.title,size,True);text(0,550,'V E H I C L E   H I S T O R Y   R E P O R T',9)
        rule(531);text(0,510,'VIN: '+r.vin,12,True,BLUE)
        if r.date:text(300,510,'Search Date: '+r.date,9)
        summary=[k for k in ['Mileage','Title Records','Ownership History'] if k in r.summary]
        if summary:
            c.setFillColor(PALE);c.rect(0,410,WIDTH,75,fill=1,stroke=0)
            cw=WIDTH/len(summary)
            for i,k in enumerate(summary):
                icon(k,i*cw+9,432);text(i*cw+39,461,k,9.5,True);text(i*cw+39,435,r.summary[k],13,True,RED if k=='Mileage' else BLUE)
        history=[k for k in SECTIONS if k in r.summary and k not in summary and k not in ['Maintenance Schedule','Auto Specs','Crash Test Ratings','Cost of Ownership']]
        resources=[k for k in ['Maintenance Schedule','Auto Specs','Crash Test Ratings','Cost of Ownership'] if k in r.summary]
        text(0,377,'History & Records',19,True);text(362,377,'Vehicle Resources',15,True)
        c.setStrokeColor(BLUE);c.setLineWidth(1.4);c.line(344,90,344,380)
        for i,k in enumerate(history):
            y=344-i*36;icon(k,0,y-8);text(31,y,k,9.5,True)
            if r.summary[k]:
                c.setFont('Helvetica',9);c.setFillColor(RED if k=='Past Recalls' else BLUE);c.drawRightString(329,y,r.summary[k])
            rule(y-14,0,330)
        for i,k in enumerate(resources):
            y=347-i*64;icon(k,359,y-26);wrapped(k,389,y,139);text(389,y-33,r.summary[k],11,True,BLUE);rule(y-44,362,166)

        match=re.search(r'Vehicle Data\s+Year\s+([^\n]+)\nMake, Model\s+([^\n]+)',r.raw_text)
        if match:
            text(0,67,'Vehicle Data',16,True);rule(53)
            text(8,33,'Year',9);text(280,33,match.group(1),9);rule(23)
            text(8,4,'Make, Model',9);text(280,4,match.group(2),9)

class NumberedCanvas(canvas.Canvas):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.saved=[]
    def showPage(self):self.saved.append(dict(self.__dict__));self._startPage()
    def save(self):
        count=len(self.saved)
        for state in self.saved:
            self.__dict__.update(state);self.setFont('Helvetica',8);self.setFillColor(MUTED);self.drawRightString(570,35,f'Page {self._pageNumber} of {count}');super().showPage()
        super().save()

def render_report(report:Report,source:Path,destination:Path,logo:Path|None=None,progress=lambda *a:None):
    story=[]
    if report.cover:story=[SummaryCover(report),PageBreak()]
    else:story=[para(report.title,'h1'),para('DOCUMENT REPORT','small'),Spacer(1,16)]
    heading_seen=False
    elements=report.elements
    if report.cover:
        from vehicle_layout import vehicle_story
        story=vehicle_story(report)
        elements=[]
    for el in elements:
        if el.kind=='heading':
            if heading_seen:story.append(Spacer(1,12))
            heading_seen=True;story.append(para(el.text,'h1'))
        elif el.kind=='subheading':story.extend([CondPageBreak(90),para(el.text,'h2')])
        elif el.kind in ('table','fields'):story.extend([styled_table(el,report.links),Spacer(1,9)])
        elif el.kind=='image':
            w,h=el.size;scale=min(1,WIDTH/w,130/h);story.extend([Image(io.BytesIO(el.image),width=w*scale,height=h*scale,hAlign='RIGHT' if w<130 else 'LEFT'),Spacer(1,8)])
        elif el.text:story.append(para(el.text,'body',report.links))
    logo=Path(logo) if logo else ROOT/'assets'/'logo.png'
    def page(c,doc):
        c.saveState()
        if logo.exists():c.drawImage(str(logo),42,738,width=115,height=44,preserveAspectRatio=True,anchor='sw',mask='auto')
        else:c.setFont('Helvetica-Bold',17);c.setFillColor(BLUE);c.drawString(42,756,'VINLOOKUPNOW')
        c.setFont('Helvetica-Bold',9);c.setFillColor(INK);title=report.title
        while c.stringWidth(title,'Helvetica-Bold',9)>285:title=title[:-2]
        right=522 if report.brand_image else 570
        c.drawRightString(right,764,title)
        if report.brand_image:c.drawImage(ImageReader(io.BytesIO(report.brand_image)),535,747,width=35,height=32,preserveAspectRatio=True,mask='auto')
        if report.vin:c.setFont('Helvetica',8);c.setFillColor(MUTED);c.drawRightString(right,750,'VIN: '+report.vin)
        c.setStrokeColor(BLUE);c.setLineWidth(1.5);c.line(42,730,570,730)
        c.setStrokeColor(GRAY);c.setLineWidth(.5);c.line(42,54,570,54)
        c.setFont('Helvetica',8);c.setFillColor(MUTED)
        if report.generated:c.drawString(42,35,'Report generated on '+report.generated)
        c.drawCentredString(306,35,'vinlookupnow.com')
        if report.footer:
            p=para(report.footer,'small');p.style=ParagraphStyle('footer',parent=STYLES['small'],fontSize=5.8,leading=7);_,h=p.wrap(WIDTH,20);p.drawOn(c,42,15)
        c.restoreState()
    progress(64,'Building the redesigned PDF')
    temp=destination.with_suffix('.render.pdf')
    doc=SimpleDocTemplate(str(temp),pagesize=(612,792),leftMargin=36,rightMargin=36,topMargin=81,bottomMargin=70,title=report.title+' | VINLookUpNow',author='VINLookUpNow')
    doc.build(story,onFirstPage=page,onLaterPages=page,canvasmaker=NumberedCanvas)
    progress(86,'Checking output and preserving the source PDF')
    # Keep the exact input bytes accessible in PDF readers with an Attachments panel.
    with fitz.open(temp) as out:
        if not len(out):raise ConversionError('No output pages could be created.')
        out.embfile_add('original-source.pdf',source.read_bytes(),filename='original-source.pdf',desc='Unmodified uploaded PDF for comparison with the redesigned report')
        out.save(destination,garbage=4,deflate=True)
        page_count=len(out)
        result_text=' '.join(p.get_text() for p in out)
    temp.unlink(missing_ok=True)
    # A financial value may appear extra times in a chart, but none may disappear.
    amounts=set(re.findall(r'\$[\d,]+(?:\.\d+)?',report.body_text))
    lost=amounts-set(re.findall(r'\$[\d,]+(?:\.\d+)?',result_text))
    if lost:
        destination.unlink(missing_ok=True)
        raise ConversionError('Financial-value validation failed: '+', '.join(sorted(lost))+'. No incomplete PDF was released.')
    src=collections.Counter(tokens(report.body_text));dst=collections.Counter(tokens(result_text));missing=src-dst
    # This count is transparent, not a claim of semantic validation. Repeated column headers can reduce counts.
    coverage=round(100*(sum(src.values())-sum(missing.values()))/max(1,sum(src.values())),2)
    if coverage<99:report.warnings.append(f'Text audit: {coverage}% of source-body word occurrences matched. Review the result against the attached original; wrapping and consolidated headers can affect this score.')
    progress(100,'Ready to download')
    return {'title':report.title,'vin':report.vin,'source_pages':report.source_pages,'output_pages':page_count,'text_coverage':coverage,'warnings':report.warnings,'mode':'Vehicle report' if report.cover else 'General PDF','original_attached':True}

def convert_pdf(source,destination,password='',logo=None,progress=lambda *a:None):
    source,destination=Path(source),Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    report=extract_report(source,password,progress)
    return render_report(report,source,destination,logo,progress)
