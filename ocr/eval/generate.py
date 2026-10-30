"""Render synthetic OCR inputs and ground truth; no OCR or test assertions."""
from __future__ import annotations
import argparse, hashlib, io, json, os
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter
ROOT=Path(__file__).resolve().parent


def font_path():
    candidates=[os.environ.get('SIGNSPEAK_TEST_FONT'), '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                r'C:\Windows\Fonts\arial.ttf',r'C:\Windows\Fonts\segoeui.ttf']
    return next((Path(p) for p in candidates if p and Path(p).is_file()),None)


def generate(output: Path, font: Path, seed=1729):
    en='The library is closed on Monday.\nIt reopens Tuesday at 9:00 AM.'
    fr='La bibliothèque est fermée lundi.\nElle rouvre mardi à 9 h 00.'
    bi='The library reopens Tuesday at 9:00 AM.\nLa bibliothèque rouvre mardi à 9 h 00.'
    nutrition='Nutrition Facts / Valeur nutritive\nPer 125 g / pour 125 g\nCalories 120\nFat 1.5 g 2%\nSodium 230 mg 10%'
    numbers='Temperature -12.5 C. Distance 0.75 km.\nVolume 250 mL. Weight 2,5 kg.'
    columns=['ENGLISH NOTICE\nOpen Tuesday at 9:00 AM.\nAdmission $12.50.\nChildren under 5 enter free.',
             'AVIS EN FRANÇAIS\nOuvert mardi à 9 h 00.\nEntrée 12,50 $.\nGratuit pour les moins de 5 ans.']
    # Explicit fixed development set: content and perturbations do not depend on
    # OCR outputs. Photography-like conditions are simulations, not photographs.
    specs=[('english_clean',[en],28,[]),('french_clean',[fr],28,[]),('bilingual_clean',[bi],28,[]),
           ('nutrition_clean',[nutrition],24,[]),('english_dark',[en],28,['dark']),
           ('french_dark',[fr],28,['dark','jpeg']),('english_low',[en],28,['low','jpeg']),
           ('french_low',[fr],28,['low','noise','jpeg']),('english_shadow',[en],28,['shadow']),
           ('french_shadow',[fr],28,['shadow']),('bilingual_shadow',[bi],28,['shadow']),
           ('small_clean',['Serving size 125 g. Sodium 230 mg.\nTotal fat 1.5 g. Daily value 10%.'],12,[]),
           ('small_photo',['Portion 125 g. Sodium 230 mg.\nLipides 1,5 g. Valeur quotidienne 10%.'],14,['uneven','perspective','rotate','blur','jpeg']),
           ('nutrition_shadow',[nutrition],24,['shadow']),('nutrition_photo',[nutrition],24,['uneven','perspective','rotate','blur','noise','jpeg']),
           ('columns_clean',columns,24,[]),('columns_photo',columns,24,['shadow','perspective','rotate','jpeg']),
           ('numbers_perspective',[numbers],26,['perspective','jpeg']),
           ('numbers_rotation',[numbers],26,['rotate','low','noise','jpeg']),
           ('blurred_shadow',['No parking from 8:00 AM to 6:00 PM.\nFine $85.00. Permit zone 12.'],20,['shadow','blur','jpeg'])]
    (output/'images').mkdir(parents=True,exist_ok=True)
    (output/'ground_truth').mkdir(exist_ok=True)
    manifest=[]
    for index,(name,blocks,size,effects) in enumerate(specs):
        rng=np.random.default_rng(seed+index)
        width=1200 if len(blocks)>1 else 1000
        height=max(260,100+(size+22)*max(len(t.splitlines()) for t in blocks))
        image=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(image);font_obj=ImageFont.truetype(str(font),size)
        words=[]
        for column,block in enumerate(blocks):
            for line_no,line in enumerate(block.splitlines()):
                x=40+column*600;y=40+line_no*(size+22)
                for token in line.split():
                    bbox=list(draw.textbbox((x,y),token,font=font_obj))
                    if bbox[2] >= (600 if len(blocks)>1 and column==0 else width)-20:raise ValueError(f'Text clipped: {name}: {token}')
                    draw.text((x,y),token,font=font_obj,fill='black')
                    words.append({'text':token,'bbox':bbox,'column':column,'line':line_no})
                    x+=draw.textlength(token+' ',font=font_obj)
        array=np.asarray(image,dtype=float);matrix=np.eye(3);parameters={}
        if 'dark' in effects:array=255-array
        if 'shadow' in effects:array*=np.linspace(.12,1,width)[None,:,None]
        if 'uneven' in effects:
            xx=np.linspace(0,1,width);yy=np.linspace(0,1,height)
            array*=(.2+.8*(.65*xx[None,:]+.35*yy[:,None]))[:,:,None]
        if 'low' in effects:array=185+array*.20
        if 'noise' in effects:array+=rng.normal(0,2.0,array.shape[:2])[:,:,None]
        array=np.clip(array,0,255).astype('uint8')
        if 'perspective' in effects:
            source=np.float32([[0,0],[width,0],[width,height],[0,height]])
            # Receding right-hand edge, modest camera tilt. Keep all text in frame.
            destination=np.float32([[12,12],[width-20,25],[width-8,height-18],[24,height-8]])
            perspective=cv2.getPerspectiveTransform(source,destination)
            array=cv2.warpPerspective(array,perspective,(width,height),borderValue=(235,235,235))
            matrix=perspective@matrix;parameters['perspective_destination']=destination.tolist()
        if 'rotate' in effects:
            angle=float(rng.uniform(-1.8,1.8));rotation=cv2.getRotationMatrix2D((width/2,height/2),angle,1)
            array=cv2.warpAffine(array,rotation,(width,height),borderValue=(235,235,235))
            matrix=np.vstack([rotation,[0,0,1]])@matrix;parameters['rotation_degrees']=angle
        image=Image.fromarray(array)
        if 'blur' in effects:image=image.filter(ImageFilter.GaussianBlur(.6));parameters['blur_sigma']=.6
        if 'jpeg' in effects:
            buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=48,subsampling=2)
            image=Image.open(io.BytesIO(buffer.getvalue())).convert('RGB');parameters['jpeg_quality']=48
        for word in words:
            x0,y0,x1,y1=word['bbox'];points=np.array([[x0,y0,1],[x1,y0,1],[x1,y1,1],[x0,y1,1]],float)@matrix.T
            points=points[:,:2]/points[:,2,None]
            if (points[:,0]<0).any() or (points[:,0]>width).any() or (points[:,1]<0).any() or (points[:,1]>height).any():raise ValueError('Ground-truth word clipped')
            word['polygon']=points.tolist();word['bbox']=[float(points[:,0].min()),float(points[:,1].min()),float(points[:,0].max()),float(points[:,1].max())]
        path=output/'images'/f'{name}.png';image.save(path)
        text='\n\n'.join(blocks)
        (output/'ground_truth'/f'{name}.txt').write_text(text+'\n',encoding='utf-8')
        manifest.append({'id':name,'image':str(path.resolve()),'text':text,'words':words,'origin':'synthetic',
                         'condition':'+'.join(effects) or 'clean','effects':effects,'parameters':parameters,
                         'reading_order':'left column completely, then right column' if len(blocks)>1 else 'top to bottom',
                         'seed':seed+index,'render_to_image':matrix.tolist(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    (output/'generation.json').write_text(json.dumps({'seed':seed,'font':str(font),'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),
                                                   'opencv':cv2.__version__,'numpy':np.__version__,'cases':len(manifest)},indent=2))
    print(f'Generated {len(manifest)} images and automatic ground truth in {output}')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'generated');parser.add_argument('--font',type=Path,default=font_path());parser.add_argument('--seed',type=int,default=1729)
    args=parser.parse_args()
    if args.font is None:parser.error('Supply --font or SIGNSPEAK_TEST_FONT with an accented-character-capable TrueType font')
    generate(args.output,args.font,args.seed)
