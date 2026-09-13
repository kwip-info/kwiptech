import { motionRecipe } from './motion.mjs';
export const palettes = ['paper', 'cobalt', 'citrus', 'rose', 'mint', 'ember', 'kwip', 'midnight', 'lavender', 'poolside', 'peach', 'newsprint'];
export const styles = ['studio', 'blueprint', 'postcard', 'headline', 'cinema'];
export const worlds = {
  everything: null,
  nature: ['nature', 'plants', 'ocean', 'weather', 'landscapes'],
  science: ['space', 'science', 'microscopic', 'patterns'],
  human: ['objects', 'architecture', 'infrastructure', 'transport', 'music', 'sport', 'food'],
  time: ['history', 'maps', 'art'],
  dream: ['imagination', 'patterns', 'microscopic', 'space'],
};
export function randomSeed() { return crypto.getRandomValues(new Uint32Array(1))[0]; }
export function seeded(seed) {
  return () => { let t = seed += 0x6D2B79F5; t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
export class Bag {
  constructor(values, random) { this.values = [...values]; this.random = random; this.queue = []; this.last = null; }
  next() {
    if (!this.values.length) throw new Error('Empty content pool');
    if (!this.queue.length) {
      this.queue = [...this.values];
      for (let i = this.queue.length - 1; i > 0; i--) {
        const j = Math.floor(this.random() * (i + 1));
        [this.queue[i], this.queue[j]] = [this.queue[j], this.queue[i]];
      }
      if (this.queue.length > 1 && this.queue.at(-1) === this.last) {
        [this.queue[0], this.queue[this.queue.length - 1]] = [this.queue.at(-1), this.queue[0]];
      }
    }
    return this.last = this.queue.pop();
  }
}
export class Ride {
  constructor(items, { seed = randomSeed(), mode = 'mixed', palette = 'random', style = 'random', world = 'everything' } = {}) {
    if (!['mixed', 'image', 'prompt'].includes(mode) || !['random', ...palettes].includes(palette) || !['random', ...styles].includes(style) || !(world in worlds)) throw new Error('Invalid presentation settings');
    this.motionRandom = seeded(seed ^ 0x4B574950); this.lastTransition = null;
    this.seed = seed; this.random = seeded(seed); this.palette = palette; this.mode = mode; this.style = style; this.world = world;
    const subjects = worlds[world];
    const eligible = items.filter(i => (mode === 'mixed' || i.kind === mode) && (!subjects || i.kind !== 'image' || subjects.includes(i.topic)));
    if (!eligible.length) throw new Error('No slides match these settings');
    this.kinds = [...new Set(eligible.map(i => i.kind))];
    this.pools = {}; this.topics = {};
    for (const kind of this.kinds) {
      const values = eligible.filter(i => i.kind === kind);
      this.topics[kind] = new Bag([...new Set(values.map(i => i.topic))], this.random);
      for (const topic of this.topics[kind].values) this.pools[`${kind}:${topic}`] = new Bag(values.filter(i => i.topic === topic), this.random);
    }
    this.colors = new Bag(palettes, this.random);
    this.styles = new Bag(styles, this.random);
    this.layouts = { image: new Bag(['split', 'gallery', 'reverse', 'exhibit'], this.random), prompt: new Bag(['center', 'poster', 'rule', 'statement'], this.random), chart: new Bag(['chart', 'chart-wide'], this.random) };
    this.recent = [];
  }
  next() {
    // Independent draws avoid a detectable image / prompt / chart rotation.
    const weights = { image: .62, prompt: .28, chart: .10 };
    let draw = this.random() * this.kinds.reduce((sum, kind) => sum + weights[kind], 0);
    const kind = this.kinds.find(kind => (draw -= weights[kind]) < 0) || this.kinds.at(-1);
    const topic = this.topics[kind].next();
    const pool = this.pools[`${kind}:${topic}`];
    // Use the largest possible recent exclusion window without exhausting a small pool.
    const excluded = this.recent.slice(-Math.min(60, pool.values.length - 1));
    let item = pool.next();
    for (let tries = 0; tries < pool.values.length * 2 && excluded.includes(item.id); tries++) item = pool.next();
    if (item.id === this.recent.at(-1) && pool.values.length > 1) {
      item = pool.values.find(candidate => candidate.id !== item.id);
    }
    this.recent.push(item.id); if (this.recent.length > 60) this.recent.shift();
    const motion = motionRecipe(this.motionRandom, this.lastTransition);
    this.lastTransition = motion.transition;
    return { item, motion, palette: this.palette === 'random' ? this.colors.next() : this.palette,
      style: this.style === 'random' ? this.styles.next() : this.style, layout: this.layouts[kind].next() };
  }
}
