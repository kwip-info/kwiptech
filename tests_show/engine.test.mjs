import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { Bag, Ride, seeded, palettes, styles, worlds, presentationTitle } from '../static/show/engine.mjs';
const {items} = JSON.parse(fs.readFileSync(new URL('../show/data/catalog.json',import.meta.url)));
test('shuffle exhausts bag before reuse and avoids boundary repeats',()=>{const bag=new Bag([1,2,3,4,5],seeded(42));let last;for(let run=0;run<100;run++){const cycle=Array.from({length:5},()=>bag.next());assert.equal(new Set(cycle).size,5);assert.notEqual(cycle[0],last);last=cycle.at(-1);}});
test('same seed replays; separate seeds diverge',()=>{const sequence=seed=>{const ride=new Ride(items,{seed});return Array.from({length:100},()=>ride.next());};assert.deepEqual(sequence(9),sequence(9));assert.notDeepEqual(sequence(9),sequence(10));});
test('long rides retain variety without a fixed content cadence',()=>{const ride=new Ride(items,{seed:19});let last;const kinds={};const colors=new Set();for(let i=0;i<6000;i++){const slide=ride.next();assert.notEqual(slide.item.id,last);last=slide.item.id;kinds[slide.item.kind]=(kinds[slide.item.kind]||0)+1;colors.add(slide.palette);}assert.ok(kinds.image > 4600 && kinds.image < 5100);assert.ok(kinds.prompt > 700 && kinds.prompt < 1150);assert.ok(kinds.chart > 200 && kinds.chart < 450);assert.equal(colors.size,12);});
test('image mode and fixed palette honored',()=>{const ride=new Ride(items,{seed:8,mode:'image',palette:'paper'});for(let i=0;i<100;i++){const slide=ride.next();assert.equal(slide.item.kind,'image');assert.equal(slide.palette,'paper');}});

test('every world and visual theme has usable content',()=>{for(const world of Object.keys(worlds)){for(const style of styles){const ride=new Ride(items,{seed:17,mode:'image',world,style});for(let i=0;i<20;i++){const slide=ride.next();assert.equal(slide.style,style);assert.ok(palettes.includes(slide.palette));if(worlds[world])assert.ok(worlds[world].includes(slide.item.topic));}}}});
test('invalid and empty settings fail explicitly',()=>{assert.throws(()=>new Ride(items,{world:'missing'}));assert.throws(()=>new Ride([]));});
test('different seeds produce varied opening topics',()=>{const openers=new Set();for(let seed=0;seed<100;seed++)openers.add(new Ride(items,{seed,mode:'image'}).next().item.topic);assert.ok(openers.size>=15);});

test('mixed rides open visually and never strand the presenter in a run of text',()=>{const ride=new Ride(items,{seed:4});assert.equal(ride.next().item.kind,'image');let textRun=0;for(let i=0;i<1000;i++){textRun=ride.next().item.kind==='image'?0:textRun+1;assert.ok(textRun<=2);}});
test('presentation titles remove filename noise without mutating source credits',()=>{const item={kind:'image',topic:'nature',title:'IMG_123456789.jpg'};assert.equal(presentationTitle(item),'Nature');assert.equal(item.title,'IMG_123456789.jpg');assert.equal(presentationTitle({kind:'image',title:'A_cloud.jpg'}),'A cloud');});
