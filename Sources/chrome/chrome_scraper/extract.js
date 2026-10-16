// Runs in the page: the clean content of the rendered DOM. Returns {title, lang, description, canonical, html, text}.
// MODE ("main" | "full") and IMAGES (true | false) are put in front by the plugin.
(() => {
  const DROP = 'script,style,noscript,template,svg,canvas,iframe,object,embed,link,meta,button,input,select,textarea,' +
    'form,dialog,[hidden],[aria-hidden="true"],[role="dialog"],[role="alertdialog"]';
  const CHROME = 'nav,header,footer,aside,[role="navigation"],[role="banner"],[role="contentinfo"],[role="complementary"],' +
    '[role="search"],.breadcrumb,.breadcrumbs,.pagination,.share,.social,.related,.newsletter,.advert,.ads,.ad';
  const NOISE = /(cookie|consent|gdpr|onetrust|usercentrics|cmp-|newsletter|subscribe|paywall|modal|popup|banner-ad|sidebar|share|social|related|comment-form|skip-link)/i;

  // hidden on screen → gone (marked on the live DOM, removed from the copy)
  let n = 0;
  for (const el of document.body ? document.body.querySelectorAll('*') : []) {
    if (++n > 20000) break;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || (s.position === 'fixed' && /(cookie|consent|banner|modal|popup|overlay)/i.test(el.id + ' ' + el.className)))
      el.setAttribute('data-theron-hidden', '1');
  }
  const root = document.body ? document.body.cloneNode(true) : document.createElement('body');
  document.querySelectorAll('[data-theron-hidden]').forEach(el => el.removeAttribute('data-theron-hidden'));
  root.querySelectorAll('[data-theron-hidden]').forEach(el => el.remove());
  root.querySelectorAll(DROP).forEach(el => el.remove());

  // absolute links and pictures
  root.querySelectorAll('a[href]').forEach(a => { try { a.setAttribute('href', new URL(a.getAttribute('href'), location.href).href); } catch (e) {} });
  root.querySelectorAll('img').forEach(img => {
    const src = img.getAttribute('src') || img.getAttribute('data-src') || (img.getAttribute('srcset') || '').split(' ')[0];
    if (!IMAGES || !src || src.startsWith('data:')) { img.remove(); return; }
    try { img.setAttribute('src', new URL(src, location.href).href); } catch (e) { img.remove(); }
  });

  const textLen = el => (el.textContent || '').replace(/\s+/g, ' ').trim().length;
  const linkLen = el => [...el.querySelectorAll('a')].reduce((s, a) => s + textLen(a), 0);

  let main = root;
  if (MODE === 'main') {
    root.querySelectorAll(CHROME).forEach(el => { if (textLen(el) < 0.6 * textLen(root)) el.remove(); });
    root.querySelectorAll('div,section,ul,ol,p,span').forEach(el => {
      if (NOISE.test((el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '')) && textLen(el) < 2000) el.remove();
    });
    const total = textLen(root) || 1;
    const cands = [...root.querySelectorAll('article,main,[role="main"],[itemprop="articleBody"],#content,#main,.content,.post,.article,.entry-content,.post-content,.article-body,.markdown-body,#readme,.mw-parser-output')];
    let best = null, bestScore = 0;
    const consider = el => {
      const t = textLen(el);
      if (t < 200) return;
      const density = linkLen(el) / t;
      const score = t * (1 - Math.min(density, 0.9)) * (el.matches('article,main,[role="main"],[itemprop="articleBody"]') ? 1.3 : 1);
      if (score > bestScore) { best = el; bestScore = score; }
    };
    cands.forEach(consider);
    // a marked-up block inside the winner that holds most of its text is the real content (README in a repo page …)
    for (let again = true; again && best;) {
      again = false;
      const outer = textLen(best);
      for (const el of cands) {
        if (el !== best && best.contains(el) && textLen(el) >= 0.45 * outer && linkLen(el) / (textLen(el) || 1) < 0.5) {
          best = el; again = true; break;
        }
      }
    }
    if (!best || textLen(best) < 0.25 * total) {   // no marked-up article: the block with the most paragraph text
      const scores = new Map();
      root.querySelectorAll('p,pre,li,td,blockquote,h2,h3').forEach(p => {
        const t = textLen(p) - linkLen(p);
        if (t < 25) return;
        for (let el = p.parentElement, d = 0; el && d < 3; el = el.parentElement, d++)
          scores.set(el, (scores.get(el) || 0) + t / (d + 1));
      });
      for (const [el, s] of scores) if (s > bestScore) { best = el; bestScore = s; }
    }
    if (best && textLen(best) >= 0.15 * total) main = best;
  }
  const meta = name => (document.querySelector(`meta[name="${name}"],meta[property="${name}"]`) || {}).content || '';
  const canonical = (document.querySelector('link[rel="canonical"]') || {}).href || '';
  return {
    title: (document.title || meta('og:title') || '').trim(),
    lang: document.documentElement.lang || '',
    description: meta('description') || meta('og:description'),
    canonical,
    html: main.innerHTML,
    text: (main.innerText || main.textContent || '').trim().slice(0, 4000),
  };
})()
