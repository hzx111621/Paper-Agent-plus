<script setup lang="ts">
import { Download, ExternalLink, FileDown, FileText, Flag, Heart, LoaderCircle, RefreshCw, Search, Upload } from "lucide-vue-next";
import { ref, watch } from "vue";

import { exportSessionUrl, listSessionPapers, patchSessionPaper, reanalyzePaper, uploadPdf } from "../../api/library";
import { authHeaders } from "../../api/auth";
import { pushToast } from "../../stores/notifications";
import type { PaperRecord } from "../../types/sessions";

const props = defineProps<{ sessionKey: string; running: boolean }>();
const emit = defineEmits<{ started: [payload: { run_id: string; stream_url: string }] }>();
const papers = ref<PaperRecord[]>([]);
const stats = ref({ searched: 0, selected: 0, read_success: 0, read_failed: 0 });
const query = ref("");
const sort = ref("relevance");
const page = ref(1);
const pages = ref(0);
const total = ref(0);
const loading = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

watch(() => props.sessionKey, () => { page.value = 1; void load(); }, { immediate: true });

async function load() {
  if (!props.sessionKey) return;
  loading.value = true;
  try {
    const payload = await listSessionPapers(props.sessionKey, { query: query.value, sort: sort.value, page: page.value, page_size: 8 });
    papers.value = payload.papers;
    pages.value = payload.pages;
    total.value = payload.total;
    stats.value = payload.stats ?? stats.value;
  } catch (error) {
    pushToast({ tone: "error", title: "加载论文结果失败", description: error instanceof Error ? error.message : "请稍后再试" });
  } finally { loading.value = false; }
}

async function update(paper: PaperRecord, patch: Partial<PaperRecord>) {
  try {
    const payload = await patchSessionPaper(props.sessionKey, paper.paperId, patch);
    Object.assign(paper, payload.paper);
  } catch (error) { pushToast({ tone: "error", title: "保存论文标记失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}

async function startReanalysis(paper: PaperRecord) {
  try {
    const accepted = await reanalyzePaper(props.sessionKey, paper.paperId);
    emit("started", accepted);
  } catch (error) { pushToast({ tone: "error", title: "重新分析失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}

async function chooseFile() {
  fileInput.value?.click();
}

async function onFileChange(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  try {
    await uploadPdf(props.sessionKey, file);
    pushToast({ tone: "success", title: "PDF 已加入当前会话", description: "上传论文已保存到个人论文库，可以继续输入主题进行联合分析。" });
    await load();
  } catch (error) { pushToast({ tone: "error", title: "上传 PDF 失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
  (event.target as HTMLInputElement).value = "";
}

async function exportFile(format: string) {
  try {
    const response = await fetch(exportSessionUrl(props.sessionKey, format), { headers: authHeaders() });
    if (!response.ok) throw new Error("导出请求失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `paper-agent-${format}`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) { pushToast({ tone: "error", title: "导出失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}
</script>

<template>
  <section v-if="sessionKey" class="paper-results-panel">
    <div class="paper-results-head">
      <div><span class="eyebrow">Paper Index</span><h2>论文结果 <small>{{ total }} 篇</small></h2><p class="paper-meta">检索 {{ stats.searched }} · 保留 {{ stats.selected }} · 全文成功 {{ stats.read_success }} · 失败 {{ stats.read_failed }}</p></div>
      <div class="paper-results-actions">
        <input ref="fileInput" type="file" accept="application/pdf,.pdf" hidden @change="onFileChange" />
        <button class="button secondary compact" type="button" @click="chooseFile"><Upload :size="15" />上传 PDF</button>
        <button class="button secondary compact" type="button" @click="exportFile('md')"><FileDown :size="15" />导出综述</button>
        <button class="button secondary compact" type="button" @click="exportFile('bibtex')">BibTeX</button>
      </div>
    </div>
    <div class="paper-results-toolbar">
      <label class="paper-search"><Search :size="15" /><input v-model="query" placeholder="搜索标题、作者或摘要" @keyup.enter="page = 1; load()" /></label>
      <select v-model="sort" class="field" @change="page = 1; load()"><option value="relevance">按相关度</option><option value="year">按年份</option><option value="title">按标题</option></select>
      <button class="icon-button" type="button" aria-label="刷新论文结果" @click="load"><RefreshCw :size="15" /></button>
    </div>
    <div v-if="loading" class="paper-results-empty"><LoaderCircle class="spinning" :size="18" />正在加载论文结果…</div>
    <div v-else-if="!papers.length" class="paper-results-empty"><FileText :size="18" />当前会话还没有论文结果</div>
    <div v-else class="paper-result-list">
      <article v-for="paper in papers" :key="paper.paperId" class="paper-result-item" :data-ignored="paper.ignored">
        <div class="paper-result-copy">
          <div class="paper-result-title-row"><a :href="paper.url || paper.pdf_url || '#'" target="_blank" rel="noreferrer"><h3>{{ paper.title }}</h3><ExternalLink :size="14" /></a><span v-if="paper.relevance_score != null" class="paper-score">{{ Number(paper.relevance_score).toFixed(1) }}</span></div>
          <p class="paper-meta">{{ paper.authors.join('、') || '作者未知' }} · {{ paper.year || '年份未知' }} · {{ paper.source || '来源未知' }}</p>
          <p class="paper-abstract">{{ paper.abstract || '暂无摘要' }}</p>
          <div class="paper-result-buttons">
            <button class="icon-button" type="button" :aria-label="paper.favorite ? '取消收藏' : '收藏论文'" @click="update(paper, { favorite: !paper.favorite })"><Heart :size="15" :fill="paper.favorite ? 'currentColor' : 'none'" /></button>
            <button class="icon-button" type="button" :aria-label="paper.focused ? '取消重点阅读' : '标记重点阅读'" @click="update(paper, { focused: !paper.focused })"><Flag :size="15" :fill="paper.focused ? 'currentColor' : 'none'" /></button>
            <button class="button tertiary compact" type="button" :disabled="running" @click="startReanalysis(paper)"><RefreshCw :size="14" />重新分析</button>
            <a
              v-if="paper.pdf_url || paper.url"
              class="button secondary compact"
              :href="paper.pdf_url || paper.url"
              download
              target="_blank"
              rel="noreferrer"
              title="只下载原文，不执行总结"
            ><Download :size="14" />下载原文</a>
            <span v-if="paper.ignored" class="paper-state">已忽略</span><button class="button ghost-link compact" type="button" @click="update(paper, { ignored: !paper.ignored })">{{ paper.ignored ? '恢复' : '忽略' }}</button>
          </div>
        </div>
      </article>
    </div>
    <div class="paper-pagination"><button class="button secondary compact" :disabled="page <= 1" @click="page -= 1; load()">上一页</button><span>第 {{ page }} / {{ pages || 1 }} 页</span><button class="button secondary compact" :disabled="page >= pages" @click="page += 1; load()">下一页</button></div>
  </section>
</template>
