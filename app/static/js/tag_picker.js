import { escapeHtml } from "./common.js";

export function tagPickerHtml({
  library = [],
  selected = [],
  inherited = [],
  name = "tags",
} = {}) {
  const sel = new Set((selected || []).map((t) => String(t).toLowerCase()));
  const inh = new Set((inherited || []).map((t) => String(t).toLowerCase()));
  const known = new Set((library || []).map((t) => (t.slug || t).toLowerCase()));
  const extras = [...sel].filter((t) => !known.has(t) && !inh.has(t));
  if (!library.length && !sel.size && !inh.size) {
    return `<p class="hint" data-tag-picker="${escapeHtml(name)}">No tags yet. Create them in <a href="/admin/tags">Admin → Tags</a>.</p>`;
  }
  const chips = [];
  for (const tag of library) {
    const slug = tag.slug || tag;
    const label = tag.label || slug;
    const inheritedChip = inh.has(slug);
    chips.push(
      `<label class="tag-chip${inheritedChip ? " is-inherited" : ""}">
        <input type="checkbox" value="${escapeHtml(slug)}" ${
          sel.has(slug) || inheritedChip ? "checked" : ""
        } ${inheritedChip ? "disabled" : ""} />
        <span>${escapeHtml(label)}</span>${inheritedChip ? ' <em>category</em>' : ""}
      </label>`
    );
  }
  for (const slug of extras) {
    chips.push(
      `<label class="tag-chip">
        <input type="checkbox" value="${escapeHtml(slug)}" checked />
        <span>${escapeHtml(slug)}</span>
      </label>`
    );
  }
  for (const slug of [...inh].filter((t) => !known.has(t))) {
    chips.push(
      `<label class="tag-chip is-inherited">
        <input type="checkbox" value="${escapeHtml(slug)}" checked disabled />
        <span>${escapeHtml(slug)}</span> <em>category</em>
      </label>`
    );
  }
  return `<div class="tag-picker" data-tag-picker="${escapeHtml(name)}">${chips.join("")}</div>`;
}

export function selectedTagsFrom(root) {
  if (!root) return [];
  const box = root.matches?.("[data-tag-picker]") ? root : root.querySelector("[data-tag-picker]");
  if (!box) return [];
  return [...box.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)')].map((el) => el.value);
}

export function categoryTagsFor(program, programTags = {}) {
  const want = (program || "").trim().toLowerCase();
  if (!want) return [];
  const key = Object.keys(programTags || {}).find((name) => name.toLowerCase() === want);
  return key ? programTags[key] || [] : [];
}
