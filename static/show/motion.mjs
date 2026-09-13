// Motion has its own random stream, so changing effects never changes the content draw.
export const transitions = ['dissolve', 'push', 'rise', 'iris', 'wipe', 'zoom', 'tilt', 'curtain', 'drop', 'diagonal'];
export const entrances = ['lift', 'drift', 'scale', 'unfold', 'stagger'];
export function motionRecipe(random, previous) {
  const choices = transitions.filter(name => name !== previous);
  return {
    transition: choices[Math.floor(random() * choices.length)],
    entrance: entrances[Math.floor(random() * entrances.length)],
    direction: random() < .5 ? -1 : 1,
    duration: 430 + Math.floor(random() * 370),
    stagger: 45 + Math.floor(random() * 65),
    origin: `${20 + Math.floor(random() * 60)}% ${20 + Math.floor(random() * 60)}%`,
  };
}
export function transitionFrames(recipe) {
  const d = recipe.direction;
  switch (recipe.transition) {
    case 'push': return [{transform:`translateX(${d * 100}%)`}, {transform:'translateX(0)'}];
    case 'rise': return [{transform:`translateY(${d * 100}%)`}, {transform:'translateY(0)'}];
    case 'iris': return [{clipPath:`circle(0% at ${recipe.origin})`}, {clipPath:`circle(150% at ${recipe.origin})`}];
    case 'wipe': return [{clipPath:`inset(0 ${d === 1 ? '100% 0 0' : '0 0 100%'})`}, {clipPath:'inset(0 0 0 0)'}];
    case 'curtain': return [{clipPath:'inset(50% 0 50% 0)'}, {clipPath:'inset(0 0 0 0)'}];
    case 'zoom': return [{opacity:0,transform:'scale(.76)'}, {opacity:1,transform:'scale(1)'}];
    case 'tilt': return [{opacity:0,transform:`translateX(${d * 15}%) rotate(${d * 8}deg) scale(.92)`}, {opacity:1,transform:'translateX(0) rotate(0) scale(1)'}];
    case 'drop': return [{opacity:0,transform:'translateY(-35%) scale(.95)'}, {opacity:1,transform:'translateY(0) scale(1)'}];
    case 'diagonal': return [{clipPath:'polygon(0 0, 0 0, 0 0)'}, {clipPath:'polygon(0 0, 200% 0, 0 200%)'}];
    default: return [{opacity:0}, {opacity:1}];
  }
}
export function entranceFrames(recipe) {
  switch (recipe.entrance) {
    case 'drift': return [{opacity:0,transform:`translateX(${recipe.direction * 24}px)`}, {opacity:1,transform:'translateX(0)'}];
    case 'scale': return [{opacity:0,transform:'scale(.94)'}, {opacity:1,transform:'scale(1)'}];
    case 'stagger': return [{opacity:0,transform:'translateY(12px) scale(.98)'}, {opacity:1,transform:'translateY(0) scale(1)'}];
    case 'unfold': return [{opacity:0,transform:'perspective(800px) rotateX(-12deg)',transformOrigin:'center bottom'}, {opacity:1,transform:'perspective(800px) rotateX(0)',transformOrigin:'center bottom'}];
    default: return [{opacity:0,transform:'translateY(22px)'}, {opacity:1,transform:'translateY(0)'}];
  }
}
export function createMotionController(reduced = matchMedia('(prefers-reduced-motion: reduce)')) {
  const running = new Set();
  let host;
  function stop() {
    for (const animation of running) animation.cancel();
    running.clear();
    host?.querySelectorAll('[data-outgoing]').forEach(el => el.remove());
  }
  function animate(element, frames, options, done) {
    const animation = element.animate(frames, options);
    running.add(animation);
    animation.finished.then(() => { running.delete(animation); animation.cancel(); done?.(); }).catch(() => running.delete(animation));
  }
  function present(stage, element, recipe, mode = 'remix', beforeAnimate = () => {}) {
    stop(); host = stage;
    const previous = stage.lastElementChild;
    if (reduced.matches || mode === 'off' || typeof element.animate !== 'function') {
      stage.replaceChildren(element); beforeAnimate(); return;
    }
    const gentle = mode === 'gentle';
    const duration = gentle ? 260 : recipe.duration;
    if (previous) {
      previous.dataset.outgoing = 'true'; previous.setAttribute('aria-hidden', 'true'); previous.inert = true;
    }
    stage.append(element);
    beforeAnimate();
    animate(element, gentle ? [{opacity:0}, {opacity:1}] : transitionFrames(recipe), {
      duration, easing:'cubic-bezier(.22,.7,.2,1)', fill:'both',
    }, () => previous?.remove());
    if (!gentle) {
      const content = [...element.querySelectorAll('h2, .image-frame, .subtitle, .chart-column')];
      content.forEach((part, index) => {
        const delay = Math.round(duration * .18) + index * recipe.stagger;
        const frames = part.classList.contains('chart-column')
          ? [{opacity:0,transform:'translateY(30px)'}, {opacity:1,transform:'translateY(0)'}]
          : entranceFrames(recipe);
        animate(part, frames, {duration:Math.round(duration * .8),delay,easing:'cubic-bezier(.2,.7,.2,1)',fill:'both'});
      });
    }
  }
  reduced.addEventListener('change', stop);
  return { present, stop };
}
