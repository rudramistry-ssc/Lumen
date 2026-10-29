"""Targeted crops/upscaling with invertible geometry and bounded OCR calls."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import time
from PIL import Image

from .geometry import apply_matrix
from .tsv import parse_tsv,TsvDocument
from .tesseract import run_tesseract_tsv,TesseractRun


def targeted_read(image,layout,scale,config,info,deadline,calls_left):
    import numpy as np
    crops=layout['columns'] or [(0,0,image.width,image.height)]
    if len(crops)>calls_left:raise ValueError('targeted_call_budget')
    blocks=[];commands=[];tsvs=[];transforms=[];rows=word_rows=empty=malformed=0;warnings=[]
    for region_index,(x0,y0,x1,y1) in enumerate(crops):
        crop=image.crop((x0,y0,x1,y1))
        target=(max(1,round(crop.width*scale)),max(1,round(crop.height*scale)))
        if target[0]*target[1]>config.preprocessing.max_pixels:raise ValueError('targeted_pixel_budget')
        crop=crop.resize(target,Image.Resampling.LANCZOS) if target!=crop.size else crop
        remaining=deadline-time.perf_counter()
        if remaining<=0:raise TimeoutError('targeted_time_budget')
        psm=6  # A detected column or compact small-text notice, never full-page forced PSM.
        run=run_tesseract_tsv(crop,replace(config.tesseract,psm=psm,timeout_seconds=min(remaining,config.tesseract.timeout_seconds)),info)
        doc=parse_tsv(run.tsv);sx=target[0]/(x1-x0);sy=target[1]/(y1-y0)
        inverse=np.array([[1/sx,0,x0],[0,1/sy,y0],[0,0,1]],float)
        transforms.append({'source_region':region_index,'crop_bbox_working':[x0,y0,x1,y1],
                           'ocr_size':list(target),'ocr_to_working':inverse.tolist(),'psm':psm})
        def map_box(box):
            if box is None:return None
            pts=apply_matrix(inverse,[(box[0],box[1]),(box[2],box[3])])
            return (*pts[0],*pts[1])
        for block in doc.blocks:
            block=deepcopy(block);block.bbox=map_box(block.bbox)
            block.provenance={'stage':'targeted_ocr','psm':psm,'source_region':region_index,
                              'crop_bbox_working':[x0,y0,x1,y1],'ocr_size':list(target),
                              'working_to_ocr':[[sx,0,-x0*sx],[0,sy,-y0*sy],[0,0,1]],
                              'ocr_to_working':inverse.tolist(),'scale':[sx,sy]}
            for paragraph in block.paragraphs:
                paragraph.bbox=map_box(paragraph.bbox)
                for line in paragraph.lines:
                    line.bbox=map_box(line.bbox)
                    for word in line.words:word.bbox=map_box(word.bbox)
            blocks.append(block)
        commands.append(run.command);tsvs.append(run.tsv);warnings.extend(doc.warnings)
        rows+=doc.row_count;word_rows+=doc.word_row_count;empty+=doc.empty_word_rows;malformed+=doc.malformed_rows
    combined=TsvDocument(image.size,blocks,rows,word_rows,empty,malformed,warnings)
    # Per-crop TSVs and transforms are retained separately; no fabricated merged TSV.
    aggregate=TesseractRun('',commands[0],0,[],0,image.size)
    return combined,aggregate,{'commands':commands,'raw_tsvs':tsvs,'calls':len(crops),'scale':scale,'columns':layout['columns'],'region_transforms':transforms}
