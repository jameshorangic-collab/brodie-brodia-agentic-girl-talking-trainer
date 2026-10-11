export const SCENES = {
  barista: { label: 'Coffee shop', name: 'Jess', avatar: 'jess', interested: 'Ha, nobody ever asks me that. Oat flat white, honestly.', neutral: 'Sure, what can I get started for you?', uninterested: 'Next in line? Sorry, it’s a bit hectic right now.' },
  street: { label: 'Street', name: 'Nadia', avatar: 'nadia', interested: 'Oh, hi! No, you’re fine. I’ve got a minute.', neutral: 'Uh, hi? Can I help you with something?', uninterested: 'Sorry, I’m running late for something.' },
  park: { label: 'Park', name: 'Maya', avatar: 'maya', interested: 'It’s a library book, actually. Have you read anything by her?', neutral: 'Hey. Yeah, it’s a nice day for it.', uninterested: 'I’m kind of just trying to read, sorry.' },
};

/* per difficulty: label, hint, eval bar share (%), eval label, and the grade your last move earned */
export const MODES = {
  interested: { label: 'Easy', lead: 'She’s into it.', hint: 'Don’t fumble.', bar: 72, num: '+1.4', grade: 'brill' },
  neutral: { label: 'Mid', lead: 'Mid energy.', hint: 'Earn it.', bar: 54, num: '+0.3', grade: 'great' },
  uninterested: { label: 'Not interested', lead: 'Not it.', hint: 'Dip clean = +aura.', bar: 34, num: '−0.8', grade: 'best' },
};

export const GRADES = {
  brill: { sym: '!!', name: 'Brilliant' },
  great: { sym: '!', name: 'Great' },
  best: { sym: '★', name: 'Best' },
  inacc: { sym: '?!', name: 'Inaccuracy' },
  mist: { sym: '?', name: 'Mistake' },
  blund: { sym: '??', name: 'Blunder' },
};

export const SAMPLE_MOVES = [
  { ts: '0:02', grade: 'brill', text: 'Opened on her book. Zero script.' },
  { ts: '0:04', grade: 'inacc', text: 'Looked away on the hello.', cam: true },
  { ts: '0:19', grade: 'great', text: 'Let her finish. Aura.' },
  { ts: '0:51', grade: 'mist', quote: 'Come here often?', text: 'NPC line.' },
  { ts: '1:30', grade: 'best', text: 'Read the room. Dipped clean.' },
];

/* Feature centers in each 612x408 avatar render; copied from assets/avatar/brodia-avatars.json. */
export const AVATARS = {
  maya: { eyes: [[268, 232], [352, 232]], brows: [[268, 203], [352, 203]], mouth: [310, 284] },
  jess: { eyes: [[245, 220], [378, 220]], brows: [[245, 182], [378, 182]], mouth: [312, 284] },
  nadia: { eyes: [[272, 228], [358, 228]], brows: [[272, 200], [358, 200]], mouth: [315, 280] },
};
