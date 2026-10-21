<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import type { PaperRecord } from "../types/sessions";

type Reading = { markdown: string; complete: boolean; chapters: { title_zh: string }[]; rounds: { title: string }[] };
type SummaryImage = { data_url: string; summary: string; model: string; language: string; mime: string };
type Payload = { reading: Reading | null; image: SummaryImage | null; running?: boolean };
const props = defineProps<{ paper: PaperRecord; initialTab?: "reading" | "image" }>();
const emit = defineEmits<{ close: [] }>();
const tab = ref(props.initialTab || "reading");
const result = ref<Payload>({ reading: null, image: null });
const busy = ref(false);
const loading = ref(true);
const errorMessage = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
const url = `/api/library/${encodeURIComponent(props.paper.paperId)}/reading`;

async function request(path: string, method = "GET"): Promise<Payload> {
  const response = await fetch(path, { method });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || "论文处理失败");
  return body as Payload;
}

async function load() {
  try {
    result.value = await request(url);
    busy.value = Boolean(result.value.running);
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : "读取失败"; }
  finally { loading.value = false; }
}

// 精读每完成一轮都会落盘，轮询只查看已有结果，不会再次调用模型。
async function poll() {
  if (disposed) return;
  try {
    result.value = await request(url);
    // 页面刷新后也能识别后台请求已结束，恢复按钮，允许继续未完成的轮次。
    if (result.value.running === false) busy.value = false;
  } catch { /* 临时读取失败时保留当前显示的笔记。 */ }
  if (!disposed && busy.value) timer = setTimeout(poll, 3000);
}

async function generate() {
  busy.value = true;
  errorMessage.value = "";
  timer = setTimeout(poll, 3000);
  try { result.value = await request(`${url}/${tab.value}`, "POST"); }
  catch (error) { errorMessage.value = error instanceof Error ? error.message : "生成失败，请重试"; }
  finally { busy.value = false; clearTimeout(timer); }
}

function downloadNote() {
  const objectUrl = URL.createObjectURL(new Blob([result.value.reading?.markdown || ""], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = "论文精读.md";
  link.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

onMounted(async () => { await load(); if (busy.value) timer = setTimeout(poll, 3000); });
onBeforeUnmount(() => { disposed = true; clearTimeout(timer); });
</script>

<template>
  <Teleport to="body">
    <div class="session-delete-dialog-backdrop">
      <section class="editor-card paper-reading-dialog" role="dialog" aria-modal="true" aria-labelledby="paper-reading-title">
        <div class="editor-head"><div><h2 id="paper-reading-title">论文精读与一图总结</h2><p>{{ paper.title }}</p></div><button class="button secondary compact" :disabled="busy" @click="emit('close')">关闭</button></div>
        <div class="paper-reading-actions"><button class="button compact" :class="tab === 'reading' ? 'primary' : 'secondary'" :disabled="busy" @click="tab = 'reading'">双阶段精读</button><button class="button compact" :class="tab === 'image' ? 'primary' : 'secondary'" :disabled="busy" @click="tab = 'image'">一图总结</button></div>
        <p v-if="tab === 'reading'" class="paper-meta">先识别最多 12 个章节，逐章阅读后进行“核心贡献判断”和“局限与疑问”追问。中断后可继续已保存的进度。</p>
        <p v-else class="paper-meta">阅读全文提取视觉信息，再生成一张学术概念海报。请先在设置页填写生图模型；点击生成会调用你配置的服务。</p>
        <p v-if="errorMessage" class="reading-error" role="alert">{{ errorMessage }}</p>
        <div class="paper-reading-actions">
          <button class="button primary" :disabled="busy || loading || (tab === 'reading' && result.reading?.complete)" @click="generate">{{ busy ? '正在处理，请稍候…' : tab === 'image' ? (result.image ? '重新生成图片' : '生成一图总结') : result.reading?.complete ? '精读已完成' : result.reading?.rounds.length ? '继续精读' : '开始精读' }}</button>
          <button v-if="tab === 'reading' && result.reading?.markdown" class="button secondary" @click="downloadNote">下载 Markdown</button>
          <a v-if="tab === 'image' && result.image" class="button secondary" :href="result.image.data_url" :download="`一图总结.${result.image.mime === 'image/jpeg' ? 'jpg' : result.image.mime === 'image/webp' ? 'webp' : 'png'}`">下载图片</a>
        </div>
        <div v-if="tab === 'reading'" class="paper-reading-content">
          <p v-if="result.reading">已完成 {{ result.reading.rounds.length }} / {{ result.reading.chapters.length + 2 }} 轮</p>
          <pre v-if="result.reading?.markdown">{{ result.reading.markdown }}</pre>
          <p v-else>{{ loading ? '正在读取笔记…' : busy ? '正在获取全文或识别章节…' : '尚未生成精读笔记。' }}</p>
        </div>
        <div v-else class="paper-reading-content">
          <template v-if="result.image"><img :src="result.image.data_url" alt="论文一图总结" /><p class="paper-meta">{{ result.image.model }} · {{ result.image.language }}</p><details><summary>查看视觉信息提取结果</summary><pre>{{ result.image.summary }}</pre></details></template>
          <p v-else>{{ busy ? '正在提取视觉信息并生成图片，通常需要几分钟…' : '尚未生成一图总结。' }}</p>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.paper-reading-dialog { width: min(1080px, 94vw); max-height: 92vh; display: flex; flex-direction: column; gap: 14px; overflow: auto; }
.editor-head { align-items: flex-start; gap: 16px; }
.editor-head h2 { margin: 0 0 8px; }
.paper-reading-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.paper-reading-content { min-height: 120px; }
.paper-reading-content pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; line-height: 1.8; }
.paper-reading-content img { display: block; width: 100%; border-radius: 12px; }
.reading-error { color: #b42318; }
</style>
