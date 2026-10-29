"""Bounded classical text-size and two-column evidence, without model inference."""
from __future__ import annotations
import numpy as np


def analyze_layout(image):
    import cv2
    gray=np.asarray(image.convert('L'))
    mask=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,10)
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    boxes=[]
    for x,y,w,h,area in stats[1:]:
        if 3<=h<=min(80,image.height*.25) and area>=4 and .1<=w/h<=8:
            boxes.append((int(x),int(y),int(x+w),int(y+h)))
    if len(boxes)<12:
        return {'median_glyph_height':None,'glyph_count':len(boxes),'columns':[]}
    median=float(np.median([b[3]-b[1] for b in boxes]))
    # Union character x projections. A broad blank gutter must be internal,
    # with several aligned text rows on each side; word gaps are insufficient.
    projection=np.zeros(image.width,dtype=bool)
    for x0,y0,x1,y1 in boxes:projection[x0:x1]=True
    gaps=[];start=None
    for x in range(image.width):
        if not projection[x] and start is None:start=x
        elif projection[x] and start is not None:
            if start>0:gaps.append((start,x))
            start=None
    def row_count(items):
        centers=sorted((b[1]+b[3])/2 for b in items)
        rows=[]
        for y in centers:
            if not rows or y-rows[-1]>median*1.2:rows.append(y)
        return len(rows)
    columns=[];gutter=None
    for left,right in sorted(gaps,key=lambda g:g[1]-g[0],reverse=True):
        mid=(left+right)/2
        if right-left<max(3*median,.08*image.width) or not .25*image.width<mid<.75*image.width:continue
        a=[b for b in boxes if b[2]<=left];b=[b for b in boxes if b[0]>=right]
        if len(a)<8 or len(b)<8 or row_count(a)<2 or row_count(b)<2:continue
        ay=(min(v[1] for v in a),max(v[3] for v in a));by=(min(v[1] for v in b),max(v[3] for v in b))
        shared=max(0,min(ay[1],by[1])-max(ay[0],by[0]))/max(1,min(ay[1]-ay[0],by[1]-by[0]))
        if shared<.6:continue
        cut=int(mid);columns=[(0,0,cut,image.height),(cut,0,image.width,image.height)];gutter=[left,right];break
    return {'median_glyph_height':median,'glyph_count':len(boxes),'columns':columns,'gutter':gutter,
            'text_rows':row_count(boxes),'method':'connected_components_and_wide_gutter'}


def order_columns(document,columns):
    """Lossless assignment of existing words to disjoint columns, no OCR edits."""
    from copy import deepcopy
    from .tsv import Block,Paragraph,Line
    from .geometry import union_box
    result=deepcopy(document);result.blocks=[]
    for index,(x0,y0,x1,y1) in enumerate(columns,1):
        lines=[]
        for source_line in document.iter_lines():
            words=[deepcopy(w) for w in source_line.words if x0<=(w.bbox[0]+w.bbox[2])/2<x1]
            if words:
                words.sort(key=lambda w:w.bbox[0]);lines.append(Line((1,index,1,len(lines)+1),union_box(w.bbox for w in words),words))
        lines.sort(key=lambda line:line.bbox[1])
        if lines:
            box=union_box(line.bbox for line in lines)
            block=Block((1,index),box,[Paragraph((1,index,1),box,lines)])
            block.provenance={'stage':'column_reading_order','source_region':index-1,'crop_bbox_working':[x0,y0,x1,y1]}
            result.blocks.append(block)
    return result
