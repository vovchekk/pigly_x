import os

filepath = r'c:\Users\kvovc\Desktop\pigly\extension\content\content.js'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Lines 616 through 1042 (1-indexed) = indices 615 through 1041
before = lines[:615]  # lines 1-615
after = lines[1042:]   # lines 1043+

replacement = r'''
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatShortenResultText(text) {
    let value = String(text || "").replace(/\r/g, "").trim();
    if (!value) return "";

    value = value.replace(/[ \t]+\n/g, "\n");
    value = value.replace(/[ \t]{2,}/g, " ");
    value = value.replace(/\n{3,}/g, "\n\n");

    value = value.replace(/:\s+(@[A-Za-z0-9_])/g, ":\n$1");
    value = value.replace(/;\s+(@[A-Za-z0-9_])/g, ";\n$1");
    value = value.replace(/([.!?])\s+(@[A-Za-z0-9_])/g, "$1\n\n$2");

    value = value.replace(/\.{3,}\s*$/g, "");
    value = value.replace(/\s+\n/g, "\n");
    value = value.replace(/\n{3,}/g, "\n\n");
    return value.trim();
  }

  function buildShortenResultMarkup(text) {
    const formatted = formatShortenResultText(text);
    if (!formatted) {
      return `<div class="pigly-result-copy pigly-result-copy-plain"></div>`;
    }
    return `<div class="pigly-result-copy pigly-result-copy-plain">${escapeHtml(formatted)}</div>`;
  }

  function renderShortenResult(container, requestData) {
    if (!requestData || !requestData.results || requestData.results.length === 0) {
      renderError(container, "No shortened version was generated.");
      return;
    }
    container.innerHTML = buildShortenResultMarkup(requestData.results[0].content);
  }

  function trimWords(text, wordCount) {
    const words = normalizeInlineText(text).split(" ").filter(Boolean);
    if (!words.length) return "";
    if (words.length <= wordCount) return words.join(" ");
    return `${words.slice(0, wordCount).join(" ")}...`;
  }

'''

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(before)
    f.write(replacement)
    f.writelines(after)

with open(filepath, 'r', encoding='utf-8') as f:
    new_lines = f.readlines()

print(f"Old line count: {len(lines)}")
print(f"New line count: {len(new_lines)}")
print(f"Removed {len(lines) - len(new_lines)} lines of duplicates")
