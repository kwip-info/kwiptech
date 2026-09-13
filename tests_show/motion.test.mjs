import {test} from 'node:test';
import assert from 'node:assert/strict';
import {motionRecipe, transitions, transitionFrames, createMotionController} from '../static/show/motion.mjs';
import {seeded} from '../static/show/engine.mjs';

test('motion is varied, repeat-protected and bounded',()=>{
  const random=seeded(28), seen=new Set();let previous;
  for(let i=0;i<1000;i++){
    const recipe=motionRecipe(random,previous);
    assert.notEqual(recipe.transition,previous);
    assert.ok(recipe.duration>=430&&recipe.duration<800);
    assert.ok(recipe.stagger>=45&&recipe.stagger<110);
    assert.ok([-1,1].includes(recipe.direction));
    assert.equal(transitionFrames(recipe).length,2);
    previous=recipe.transition;seen.add(previous);
  }
  assert.deepEqual([...seen].sort(),[...transitions].sort());
});
function fixture(reduced=false){
  const animations=[];let change;
  const pref={matches:reduced,addEventListener:(name,fn)=>{change=fn;}};
  const stage={children:[],get lastElementChild(){return this.children.at(-1);},append(el){this.children.push(el);el.host=this;},replaceChildren(el){this.children=[];this.append(el);},querySelectorAll(){return this.children.filter(el=>el.dataset.outgoing);}};
  const element=()=>({dataset:{},setAttribute(){},querySelectorAll(){return [];},remove(){stage.children=stage.children.filter(el=>el!==this);},animate(){let resolve,reject;const animation={finished:new Promise((a,b)=>{resolve=a;reject=b;}),cancel(){this.canceled=true;reject();},finish(){resolve();}};animations.push(animation);return animation;}});
  return {stage,element,animations,controller:createMotionController(pref),setReduced(){pref.matches=true;change();}};
}
test('rapid navigation cancels old effects and retains only one outgoing slide',async()=>{
  const f=fixture(),recipe=motionRecipe(seeded(1));
  for(let i=0;i<25;i++){f.controller.present(f.stage,f.element(),recipe);assert.ok(f.stage.children.length<=2);}
  assert.equal(f.animations.filter(a=>!a.canceled).length,1);
  f.animations.at(-1).finish();await Promise.resolve();
  assert.equal(f.stage.children.length,1);
});
test('reduced motion and off bypass animations; a preference change settles immediately',()=>{
  for(const mode of ['off','remix']){
    const f=fixture(mode==='remix');f.controller.present(f.stage,f.element(),motionRecipe(seeded(1)),mode);
    assert.equal(f.animations.length,0);assert.equal(f.stage.children.length,1);
  }
  const f=fixture();f.controller.present(f.stage,f.element(),motionRecipe(seeded(1)));f.controller.present(f.stage,f.element(),motionRecipe(seeded(2)));
  f.setReduced();assert.equal(f.stage.children.length,1);assert.ok(f.animations.every(a=>a.canceled));
});
