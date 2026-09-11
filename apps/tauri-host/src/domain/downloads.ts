export type DownloadAnchor = {
  href: string;
  download: string;
  style: { display: string };
  click: () => void;
  remove: () => void;
};

export type DownloadDocument = {
  createElement: (tag: string) => DownloadAnchor;
  body: { append: (node: DownloadAnchor) => void };
};

export type DownloadScheduler = {
  setTimeout: (callback: () => void, delayMs: number) => unknown;
};

export function triggerDownload(
  document: Document | DownloadDocument,
  content: string,
  filename: string,
  mime: string,
  scheduler: DownloadScheduler
): void {
  const doc = document as DownloadDocument;
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const anchor = doc.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  doc.body.append(anchor);
  anchor.click();
  anchor.remove();
  scheduler.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export const TEXT_MARKDOWN_MIME = "text/markdown;charset=utf-8";

export function plainTextMime(format: "csv" | "txt"): string {
  return format === "csv" ? "text/csv;charset=utf-8" : "text/plain;charset=utf-8";
}
