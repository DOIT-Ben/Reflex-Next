export function resultMarkdownFilename(date = new Date()): string {
  const stamp = [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
    String(date.getHours()).padStart(2, "0"),
    String(date.getMinutes()).padStart(2, "0"),
    String(date.getSeconds()).padStart(2, "0")
  ].join("");
  return `reflex-result-${stamp}.md`;
}

export function resultMarkdownContent(output: string): string {
  return typeof output === "string" ? output.replace(/\r\n?/g, "\n") : "";
}
