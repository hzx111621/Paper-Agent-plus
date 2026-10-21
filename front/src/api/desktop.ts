/**
 * 中文说明：普通浏览器沿用网页下载；Windows 安装版有内置窗口时，
 * 交给桌面程序弹出“另存为”对话框，避免 WebView 忽略临时下载链接。
 */
declare global {
  interface Window {
    pywebview?: {
      api?: {
        save_export?: (filename: string, contentBase64: string) => Promise<{ saved: boolean; cancelled?: boolean; error?: string }>;
      };
    };
  }
}

export async function saveDownloadedFile(filename: string, blob: Blob): Promise<boolean> {
  const saveExport = window.pywebview?.api?.save_export;
  if (!saveExport) return false;
  const base64 = await blobToBase64(blob);
  const result = await saveExport(filename, base64);
  if (result.error) throw new Error(result.error);
  return Boolean(result.saved);
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error || new Error("无法读取导出文件"));
    reader.readAsDataURL(blob);
  });
}
