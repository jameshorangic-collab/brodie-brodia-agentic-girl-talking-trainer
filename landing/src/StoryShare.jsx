import { useEffect, useState } from 'react';
import { canShare, renderStory, saveStory, shareStory } from './story.js';

/* Preview the story card, then share it (phones: the share sheet, where Instagram / Snapchat offer "Story") or save it.
   The card is drawn before the Share button is enabled, so navigator.share runs straight from the tap (iOS needs that). */
export default function StoryShare({ report, pick, seconds, best, onClose }) {
  const [line, setLine] = useState(false);
  const [file, setFile] = useState(null);
  const [url, setUrl] = useState('');
  const [note, setNote] = useState('');

  useEffect(() => {
    let alive = true; setFile(null); setNote('');
    renderStory(report, pick, seconds, { line })
      .then((f) => { if (alive) { setFile(f); setUrl(URL.createObjectURL(f)); } })
      .catch(() => alive && setNote('Couldn’t draw the card. Try again.'));
    return () => { alive = false; };
  }, [report, pick, seconds, line]);
  useEffect(() => () => url && URL.revokeObjectURL(url), [url]);

  const sharable = canShare(file);
  async function share() {
    const r = await shareStory(file);
    if (r === 'failed') setNote('Sharing didn’t work here. Save the image and add it to your story instead.');
  }

  return (
    <div className="story" role="dialog" aria-modal="true" aria-label="Share your game review to your story">
      <div className="storycard">
        <div className="storyprev">{url && file ? <img src={url} alt="Your story card" /> : <span className="spin" aria-label="Drawing your card" />}</div>
        {best && (
          <label className="toggle">
            <input type="checkbox" checked={line} onChange={(e) => setLine(e.target.checked)} />
            <span>Add my best line</span>
          </label>
        )}
        <p className="fine">The card shows your score, grades and outcome{line ? ', plus that one line you said' : ''}. Nothing else from the call.</p>
        <div className="storyctl">
          {sharable && <button className="btn" type="button" disabled={!file} onClick={share}>Share</button>}
          <button className={`btn${sharable ? ' ghost' : ''}`} type="button" disabled={!file} onClick={() => saveStory(file)}>Save image</button>
          <button className="btn ghost" type="button" onClick={onClose}>Back</button>
        </div>
        <p className="fine">{sharable ? 'In the share sheet, pick Instagram or Snapchat, then Story.' : 'On your phone, add the saved image to your Instagram or Snapchat story.'}</p>
        {note && <p className="err" role="alert">{note}</p>}
      </div>
    </div>
  );
}
