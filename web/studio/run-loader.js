// Loading replay run files: gzip-transparent parse (fetched blob or local File pick) via the
// browser's DecompressionStream. Ported from neural-whoop-lab.

import { runFileUrl } from "./api.js";

// Parse a replay file/blob, inflating gzip (magic 0x1f 0x8b or .gz name).
export async function readRunFile(fileOrBlob, name = "") {
  const buf = new Uint8Array(await fileOrBlob.arrayBuffer());
  const fname = name || fileOrBlob.name || "";
  let text;
  if ((buf[0] === 0x1f && buf[1] === 0x8b) || fname.endsWith(".gz")) {
    const ds = new DecompressionStream("gzip");
    const stream = new Blob([buf]).stream().pipeThrough(ds);
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(buf);
  }
  const doc = JSON.parse(text);
  if (doc.format !== "neural-whoop-replay") {
    throw new Error(`Not a neural-whoop replay file (format=${doc.format}).`);
  }
  return doc;
}

// Fetch + parse a run by its runs-relative path (as returned by /api/rollout).
export async function loadRunByPath(path) {
  const res = await fetch(runFileUrl(path));
  if (!res.ok) throw new Error(`run fetch ${res.status}`);
  const blob = await res.blob();
  return readRunFile(blob, path);
}
