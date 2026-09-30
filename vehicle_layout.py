"""Structured adapter for the uploaded VINLookUpNow-style report family.
Only section/field names are recognized here. Vehicle values/counts come from input.
Unrecognized sections are rendered as source text, not discarded.
"""
import re,io
from datetime import datetime
from reportlab.platypus import PageBreak,Spacer,KeepTogether,Image,Flowable,CondPageBreak
from engine import Element,para,styled_table,SummaryCover,norm,BLUE,INK,ConversionError
from reportlab.lib import colors

MAJOR=re.compile(r'(?m)^(Vehicle Data|Mileage|Title Records|Ownership History|Junk/Salvage Records|Total Loss Records|Title Issues(?: \(Title Brands\))?|Sales History|Past Recalls|Maintenance Schedule|Auto Specs|Crash Test Ratings|Awards and Accolades|Warranties|Cost of Ownership[^\n]*|Consumer Access Product Disclaimer)\s*$')

def parse_fields(body):
    body=body.replace('Automatic Emergency\nBraking:','Automatic Emergency Braking:').replace('Pre-Collision Warning\nSystem:','Pre-Collision Warning System:')
    lines=body.splitlines(); rows=[];key=None;values=[];prefix=[]
    for line in lines:
        line=line.strip()
        if line.endswith(':'):
            if key is not None:rows.append([key,norm(' '.join(values))])
            key=line;values=[]
        elif key is None:prefix.append(line)
        else:values.append(line)
    if key is not None:rows.append([key,norm(' '.join(values))])
    return rows,norm(' '.join(prefix))

class OwnershipBars(Flowable):
    def __init__(self,labels,values):
        super().__init__();self.labels=labels;self.values=values;self.width=528;self.height=128
    def draw(self):
        c=self.canv;n=len(self.values);step=528/n;nums=[float(re.sub(r'[^0-9.]','',v)) for v in self.values];maximum=max(nums) or 1
        for i,(label,value,num) in enumerate(zip(self.labels,self.values,nums)):
            x=i*step+step*.18;width=step*.64;height=num/maximum*78
            c.setFillColor(BLUE);c.rect(x,23,width,height,fill=1,stroke=0)
            c.setFillColor(INK);c.setFont('Helvetica-Bold',9);c.drawCentredString(x+width/2,30+height,value)
            c.setFont('Helvetica',8);c.drawCentredString(x+width/2,7,label)

class DataBars(Flowable):
    """Horizontal chart with exact labels, zero baseline, no imputed observations."""
    def __init__(self,labels,values,units='',maximum=None):
        super().__init__();self.labels=labels;self.values=values;self.units=units
        self.maximum=maximum if maximum is not None else (max(values) or 1)
        self.width=528;self.height=27*len(values)+16
    def split(self,aW,aH):
        n=int((aH-16)//27)
        if n<2 or n>=len(self.values):return []
        return [DataBars(self.labels[:n],self.values[:n],self.units,self.maximum),DataBars(self.labels[n:],self.values[n:],self.units,self.maximum)]
    def draw(self):
        c=self.canv;maximum=self.maximum
        for i,(label,v) in enumerate(zip(self.labels,self.values)):
            y=self.height-26-i*27
            c.setFillColor(INK);c.setFont('Helvetica',8);c.drawString(0,y+4,label)
            c.setFillColor(colors.HexColor('#EFF7FF'));c.rect(145,y,280,14,fill=1,stroke=0)
            c.setFillColor(BLUE);c.rect(145,y,280*v/maximum,14,fill=1,stroke=0)
            c.setFillColor(INK);c.setFont('Helvetica-Bold',8)
            c.drawRightString(527,y+3,(('$' if self.units=='$' else '')+f'{v:,.0f}'+(' '+self.units if self.units and self.units!='$' else '')))


def vehicle_story(r):
    raw=r.raw_text
    raw=raw[raw.find('Vehicle Data'):]
    matches=[]
    for candidate in MAJOR.finditer(raw):
        if matches and candidate.group(1)==matches[-1].group(1):continue
        matches.append(candidate)
    sections=[]
    for i,m in enumerate(matches):
        body=raw[m.end():matches[i+1].start() if i+1<len(matches) else len(raw)].strip()
        count=''
        if re.match(r'^\d+\s*\n',body):count,body=body.split('\n',1)
        if m.group(1)!='Awards and Accolades':body=re.sub(r'(?m)^Source:[ \t]*$','',body).strip()
        sections.append((m.group(1),body,count,len(re.findall(r'(?m)^Source:[ \t]*$',raw[m.end():matches[i+1].start() if i+1<len(matches) else len(raw)]))))
    story=[SummaryCover(r),PageBreak()]
    def start(title,count='',page=True):
        story.append(CondPageBreak(100 if page else 65))
        story.append(Spacer(1,9 if page else 4))
        story.append(para(title+(' / '+count+(' record' if count=='1' else ' records') if count else ''),'h1' if page else 'h2'))
    def text(s):
        if s.strip():story.append(para(norm(s)))
    def fields(rows,header=False,widths=None):
        if rows:story.extend([styled_table(Element('table' if header else 'fields',rows=rows,widths=widths or []),r.links),Spacer(1,10)])
    def original(body):
        # Preserve unknown field layouts verbatim rather than assigning uncertain values.
        for chunk in re.split(r'\n\s*\n',body):text(chunk)
    missing_messages = {
        'Mileage': 'Not available', 'Title Records': 'None found',
        'Ownership History': 'None found', 'Junk/Salvage Records': 'None found',
        'Total Loss Records': 'None found', 'Title Issues': 'None reported',
        'Sales History': 'None found', 'Past Recalls': 'None found',
        'Awards and Accolades': 'None found', 'Warranties': 'Not available',
        'Maintenance Schedule': 'Not available', 'Auto Specs': 'Not available',
        'Crash Test Ratings': 'Not available', 'Cost of Ownership': 'Not available'
    }
    def extract_tables(first_cell):
        return [e for e in r.elements if e.kind=='table' and e.rows and norm(e.rows[0][0]).lower()==first_cell.lower()]
    source_image=next((e for e in r.elements if e.kind=='image' and e.size[0]<130 and any(x.text=='Source:' and x.page==e.page for x in r.elements)),None)
    def check_count(name,count,actual):
        if count.isdigit() and int(count)!=actual:
            raise ConversionError(f'{name}: source declares {count} records but {actual} were extracted. Conversion stopped to avoid an incomplete report.')
    for name,body,count,source_count in sections:
        if not body.strip() and not count.strip():
            body = missing_messages.get(name, 'Not available')
        if name=='Vehicle Data':
            start('Vehicle profile')
            ls=[x.strip() for x in body.splitlines() if x.strip()]
            if len(ls)%2==0:fields([ls[i:i+2] for i in range(0,len(ls),2)])
            else:original(body)
        elif name=='Mileage':
            start(name,page=False)
            front,sep,note=body.partition('Note:')
            rows,prefix=parse_fields(front);fields(rows);text(prefix)
            if sep:text('Note: '+note)
        elif name=='Title Records':
            start(name,count)
            dated=[]
            for chunk in re.split(r'(?:Current Title|Historical Title(?:[ \t]+#?\d+)?)\s*\n',body)[1:]:
                vals=dict(parse_fields(chunk)[0]);date=vals.get('Issue Date:','');miles=vals.get('Last odometer reading:','')
                try:dated.append((datetime.strptime(date,'%B %d, %Y'),int(re.sub(r'[^0-9]','',miles))))
                except ValueError:pass
            if len(dated)>1:
                dated.sort();story += [para('Data graph / Reported odometer history','h2'),DataBars([d.strftime('%b %d, %Y') for d,v in dated],[v for d,v in dated],'mi'),para('Readings from title records only. Dates are arranged chronologically; estimated mileage is excluded.','small'),Spacer(1,12)]
            pieces=list(re.finditer(r'(?m)^(Current Title|Historical Title(?:[ \t]+#?\d+)?)\s*$',body))
            check_count(name,count,len(pieces))
            if not pieces:original(body)
            for i,m in enumerate(pieces):
                chunk=body[m.end():pieces[i+1].start() if i+1<len(pieces) else len(body)]
                rows,prefix=parse_fields(chunk)
                group=[para(m.group(1),'h2')]
                if prefix:group.append(para(prefix))
                if rows:group.extend([styled_table(Element('fields',rows=rows),r.links),Spacer(1,10)])
                story.extend(group)
        elif name=='Ownership History':
            start(name,count)
            front,sep,tail=body.partition('Ownership Timeline')
            rows,prefix=parse_fields(front);text(prefix);fields(rows)
            tables=extract_tables('Owner')
            if tables:
                story.append(para('Ownership Timeline','h2'))
                for table in tables:story.extend([styled_table(table,r.links),Spacer(1,12)])
                # Retain the source's qualification after the table.
                m=re.search(r'Estimated owner count.*',tail,re.S)
                if m:text(m.group())
                elif tail and 'Owner 1' not in tail:original(tail)
            elif sep:original(tail)
        elif name in ('Junk/Salvage Records','Total Loss Records'):
            results=list(re.finditer(r'(?m)^Result #\d+[ \t]*$',body))
            check_count(name,count,len(results))
            if not results:start(name,page=False);original(body)
            else:
                note=''
                for i,m in enumerate(results):
                    if i%2==0:start(name+f' / {i+1}-{min(i+2,len(results))} of {len(results)}')
                    chunk=body[m.end():results[i+1].start() if i+1<len(results) else len(body)]
                    if 'Explanatory Note:' in chunk:chunk,note=chunk.split('Explanatory Note:',1)
                    rows,prefix=parse_fields(chunk)
                    group=[para(m.group().strip(),'h2')]
                    if prefix:group.append(para(prefix))
                    if rows:group.append(styled_table(Element('fields',rows=rows),r.links))
                    story.extend(group);story.append(Spacer(1,10))
                if note:story.append(para('Explanatory Note:','h2'));text(note)
        elif name.startswith('Title Issues'):
            # Separate actual branded-title records from the Yes/No check list.
            if body.startswith('Title Brand\n'):
                start(name,count)
                bt=extract_tables('Title Brand')
                for t in bt:
                    rows=t.rows
                    if len(rows[0])==5 and rows[0][1]=='':
                        rows=[[row[0] or row[1]]+row[2:] for row in rows]
                    fields(rows,True,[.16,.47,.16,.21])
                check=re.search(r'(?m)^Flood Damage[ \t]*$',body)
                if check:body=body[check.start():]
                else:original(body);continue
            chunks=re.split(r'\b(No|Yes|Unknown|N/A)\b',body)
            pairs=[]
            for i in range(0,len(chunks)-1,2):
                if norm(chunks[i]):pairs.append([norm(chunks[i]),chunks[i+1]])
            if pairs and not norm(chunks[-1]):
                for off in range(0,len(pairs),32):
                    start(name+(' / continued' if off else ''),count if not off else '')
                    chunk=pairs[off:off+32];half=(len(chunk)+1)//2
                    rows=[['Title brand','Status','Title brand','Status']]
                    for i in range(half):rows.append(chunk[i]+(chunk[i+half] if i+half<len(chunk) else ['','']))
                    fields(rows,True,[.4,.1,.4,.1])
            else:start(name,count);original(body)
        elif name=='Sales History':
            parts=re.split(r'(?m)^Found At:\s*\n',body)[1:]
            check_count(name,count,len(parts))
            if not parts:start(name,count);original(body)
            priced=[]
            for i,part in enumerate(parts):
                vals=dict(parse_fields('Found At:\n'+part)[0]);value=vals.get('Price:','')
                if re.fullmatch(r'\$[\d,]+(?:\.\d+)?',value):
                    priced.append((f"Listing {i+1} ({vals.get('Year:','')})",float(value.replace('$','').replace(',',''))))
            if priced:
                start('Data graph / Historical listing prices')
                story += [DataBars([x[0] for x in priced],[x[1] for x in priced],'$'),para('Recorded asking prices, not completed sales or current valuations. Listings with N/A prices are excluded.','small')]
            for i,part in enumerate(parts):
                if i%2==0:start(name+f' / {i+1}-{min(i+2,len(parts))} of {len(parts)}')
                rows,prefix=parse_fields('Found At:\n'+part)
                story.append(para(f'Listing {i+1}','h2'));text(prefix);fields(rows)
        elif name=='Past Recalls':
            records=list(re.finditer(r'(?m)^Recall #\d+\s*$',body))
            check_count(name,count,len(records))
            if not records:start(name,count);original(body)
            for i,m in enumerate(records):
                start(name+' / '+m.group().strip())
                rec=body[m.end():records[i+1].start() if i+1<len(records) else len(body)]
                rows,prefix=parse_fields(rec);text(prefix)
                metadata=[];paragraphs=[]
                for key,val in rows:
                    if key in ('Defect Description:','Defect Consequences:','Corrective Action:','Notes:'):paragraphs.append((key,val))
                    else:metadata.append([key,val])
                fields(metadata)
                for key,val in paragraphs:story.append(para(key,'h2'));text(val)
        elif name=='Maintenance Schedule':
            tables=extract_tables('Category');rows=[]
            for tb in tables:rows.extend(tb.rows[1:])
            if rows:
                start(name)
                fields([['Category','Maintenance','Interval','Notes']]+rows,True,[.16,.31,.15,.38])
            else:start(name,count);original(body)
        elif name=='Auto Specs':
            start('Vehicle specifications')
            rows,prefix=parse_fields(body);text(prefix)
            # Arrange complete key/value pairs side by side, including wrapped values.
            four=[rows[i]+(rows[i+1] if i+1<len(rows) else ['','']) for i in range(0,len(rows),2)]
            fields(four,widths=[.26,.24,.26,.24])
        elif name=='Crash Test Ratings':
            start(name,count);rows,prefix=parse_fields(body);text(prefix)
            if rows:fields([['Test','Rating']]+rows,True,[.78,.22])
        elif name=='Awards and Accolades':
            # Award titles immediately precede the Source field in this report family.
            patterns=[]
            for e in r.elements:
                if e.kind in ('heading','subheading') and e.text:
                    pattern=re.escape(e.text).replace(r'\ ',r'\s+')
                    if re.search(pattern+r'\s+Source:',body):patterns.append(pattern)
            found=list(re.finditer('('+('|'.join(patterns))+r')\s+Source:[ \t]*\n',body)) if patterns else list(re.finditer(r'(?m)^([^\n]+)\nSource:[ \t]*\n',body))
            check_count(name,count,len(found))
            if not found:start(name,count);original(body)
            for i,m in enumerate(found):
                if i%3==0:start(name+f' / {i+1}-{min(i+3,len(found))} of {len(found)}')
                rec='Source:\n'+body[m.end():found[i+1].start() if i+1<len(found) else len(body)]
                rows,prefix=parse_fields(rec)
                group=[para(m.group(1),'h2')]
                if prefix:group.append(para(prefix))
                if rows:group.extend([styled_table(Element('fields',rows=rows,widths=[.15,.85]),r.links),Spacer(1,10)])
                story.extend(group)
        elif name=='Warranties':
            start(name,count)
            tables=[]
            active=None
            for element in r.elements:
                if element.kind=='table' and element.rows and norm(element.rows[0][0]).lower()=='warranties':
                    active=Element('table',rows=[list(row) for row in element.rows],widths=element.widths,page=element.page)
                    tables.append(active)
                elif active is not None and element.kind=='table' and element.page in (active.page,active.page+1) and all(
                    len(row)==4 and row[0].strip() and re.fullmatch(r'[\d,]+|Unlimited|N/A',row[1],re.I)
                    and re.fullmatch(r'\d+ Months?|Unlimited|N/A',row[2],re.I)
                    and re.fullmatch(r'Expired|Active|N/A',row[3],re.I) for row in element.rows):
                    # Headerless continuation: preserve every row, including its first row.
                    active.rows.extend([list(row) for row in element.rows])
                    active.page=element.page
                else:
                    active=None
            if tables:check_count(name,count,sum(len(t.rows)-1 for t in tables))
            if tables:
                for table in tables:story.append(styled_table(table,r.links))
            else:original(body)
        elif name.startswith('Cost of Ownership'):
            start(name)
            # Parse the complete section across page boundaries; no header is required on continuation pages.
            lines=[x.strip() for x in body.splitlines() if x.strip()]
            heads=[];j=0
            while j<len(lines) and (re.fullmatch(r'Year \d+',lines[j]) or lines[j]=='Total'):heads.append(lines[j]);j+=1
            rows=[];label=[];vals=[]
            for line in lines[j:]:
                if re.fullmatch(r'\$[\d,]+(?:\.\d+)?',line):
                    vals.append(line)
                    if heads and len(vals)==len(heads):rows.append([' '.join(label)]+vals);label=[];vals=[]
                else:label.append(line)
            if heads and rows and not label and not vals:
                table=Element('table',rows=[['']+heads]+rows,widths=[.22]+[.78/len(heads)]*len(heads))
                total=next((row for row in rows if 'ownership' in row[0].lower() and 'cost' in row[0].lower()),None)
                indices=[i+1 for i,label in enumerate(heads) if re.fullmatch(r'Year \d+',label)]
                if total and indices:
                    story.extend([para('Data graph / Annual ownership costs','h2'),OwnershipBars([heads[i-1] for i in indices],[total[i] for i in indices]),Spacer(1,10)])
                story.append(styled_table(table,r.links))
                cats=[row for row in rows if row is not total]
                if heads[-1]=='Total' and cats:
                    story += [para('Data graph / Cost breakdown','h2'),DataBars([row[0] for row in cats],[float(row[-1].replace('$','').replace(',','')) for row in cats],'$')]
                text('Cost estimates reproduced from the source report. Graphs use the reported figures; they are not live prices.')
            else:original(body)
        elif name=='Consumer Access Product Disclaimer':
            start(name)
            active=False
            for e in r.elements:
                if e.text=='Consumer Access Product Disclaimer':active=True;continue
                if not active:continue
                if e.kind=='image':
                    w,h=e.size;scale=min(1,528/w,70/h);story.extend([Image(io.BytesIO(e.image),width=w*scale,height=h*scale,hAlign='LEFT'),Spacer(1,8)])
                elif e.text:story.append(para(e.text,'legal'))
                elif e.rows:fields(e.rows)
            if not active:original(body)
        else:start(name,count);original(body)
        if source_count and name!='Awards and Accolades':
            story.append(para('Source:','small'))
            if source_image:
                w,h=source_image.size;story.append(Image(io.BytesIO(source_image.image),width=66,height=66*h/w,hAlign='RIGHT'))
    flowed=[]
    for item in story:
        if getattr(getattr(item,'style',None),'name','')=='h2':flowed.append(CondPageBreak(65))
        flowed.append(item)
    return flowed
