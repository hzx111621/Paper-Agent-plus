<script setup lang="ts">
import { ref } from "vue";
import { listLibrary, searchImagePapers, uploadPdf } from "../../api/library";
import type { PaperRecord } from "../../types/sessions";
import PaperReadingDialog from "../PaperReadingDialog.vue";

const query = ref("");
const props = defineProps<{ ensureSession: () => Promise<string>; mode: "reading" | "image" }>();
const source = ref<"online" | "saved">("online");
const searched = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const warning = ref("");
const papers = ref<PaperRecord[]>([]);
const selected = ref<PaperRecord | null>(null);
const loading = ref(false);
const errorMessage = ref("");
const page = ref(1);
const pages = ref(0);

// 只读取当前账户已有的论文；选择后在当前页面打开生图窗口，不切换页面。
async function load() {
  loading.value = true;
  errorMessage.value = "";
  warning.value = "";
  try {
    if (source.value === "online") {
      if (!query.value.trim()) { errorMessage.value = "请输入论文标题或关键词。"; return; }
      const result = await searchImagePapers(query.value.trim());
      papers.value = result.papers;
      pages.value = 0;
      warning.value = result.unavailable_sources.length ? `部分来源暂不可用：${result.unavailable_sources.join('、')}，已显示其他来源的结果。` : "";
    } else {
      const result = await listLibrary({ query: query.value, page: page.value, page_size: 5 });
      papers.value = result.papers;
      pages.value = result.pages;
    }
    searched.value = true;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "加载论文失败，请重试";
  } finally { loading.value = false; }
}

// 上传复用当前会话，没有会话时由工作台创建，账户和历史列表保持一致。
async function onUpload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  uploading.value = true;
  errorMessage.value = "";
  try {
    if (!file.name.toLowerCase().endsWith('.pdf')) throw new Error("请选择 PDF 文件。");
    const key = await props.ensureSession();
    const result = await uploadPdf(key, file);
    selected.value = result.paper;
    warning.value = result.warnings.join('；');
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : "上传失败，请重试"; }
  finally { uploading.value = false; input.value = ""; }
}

function changeSource() {
  papers.value = [];
  page.value = 1;
  pages.value = 0;
  searched.value = false;
  errorMessage.value = "";
  warning.value = "";
  if (source.value === 'saved') void load();
}
</script>

<template>
  <section class="image-summary-picker" :aria-label="props.mode === 'reading' ? '选择精读的论文' : '选择生成一图总结的论文'">
    <p>{{ props.mode === 'reading' ? '上传本地 PDF，或在线搜索、选择资料库中的论文，然后开始精读。' : '上传 PDF，或在线搜索论文，将全文整理成一张学术概念图。' }}</p>
    <div class="image-summary-search">
      <input ref="fileInput" type="file" accept=".pdf,application/pdf" hidden @change="onUpload" />
      <button class="button secondary compact" type="button" :disabled="loading || uploading" @click="fileInput?.click()">{{ uploading ? '正在上传并解析…' : '上传 PDF' }}</button>
      <select v-model="source" class="field" aria-label="论文来源" :disabled="loading || uploading" @change="changeSource"><option value="online">在线搜索论文</option><option value="saved">选择已有论文</option></select>
    </div>
    <form class="image-summary-search" @submit.prevent="page = 1; load()">
      <input v-model="query" class="field" aria-label="论文标题或关键词" :placeholder="source === 'online' ? '输入论文标题或关键词，在线搜索' : '查找已保存的论文'" :disabled="loading || uploading" />
      <button class="button secondary compact" :disabled="loading || uploading">{{ source === 'online' ? '在线搜索' : '查找' }}</button>
    </form>
    <p v-if="loading" role="status">{{ source === 'online' ? '正在搜索在线论文来源…' : '正在读取论文…' }}</p>
    <p v-else-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <p v-else-if="searched && !papers.length">没有找到论文，请更换关键词或上传 PDF。</p>
    <div v-else-if="papers.length" class="image-summary-papers">
      <button v-for="paper in papers" :key="paper.paperId" class="image-summary-paper" type="button" :disabled="loading || uploading" @click="selected = paper">
        <span>{{ paper.title }}</span><small>{{ props.mode === 'reading' ? '选择并精读' : '选择并生成' }}</small>
      </button>
    </div>
    <p v-if="warning" role="status">{{ warning }}</p>
    <div v-if="pages > 1" class="paper-pagination">
      <button class="button secondary compact" :disabled="loading || uploading || page <= 1" @click="page--; load()">上一页</button>
      <span>{{ page }} / {{ pages }}</span>
      <button class="button secondary compact" :disabled="loading || uploading || page >= pages" @click="page++; load()">下一页</button>
    </div>
    <PaperReadingDialog v-if="selected" :paper="selected" :initial-tab="props.mode" @close="selected = null" />
  </section>
</template>

<style scoped>
.image-summary-picker { padding: 12px 18px 18px; }
.image-summary-picker > p { color: #64748b; font-size: 14px; }
.image-summary-search { display: flex; gap: 10px; margin-top: 10px; }
.image-summary-search select { flex: 1; min-width: 0; }
.image-summary-search input { flex: 1; min-width: 0; }
.image-summary-papers { display: grid; gap: 8px; margin-top: 12px; }
.image-summary-paper { display: flex; align-items: center; justify-content: space-between; gap: 16px; width: 100%; padding: 12px; border: 1px solid #e2e8f0; border-radius: 10px; background: transparent; text-align: left; color: inherit; cursor: pointer; }
.image-summary-paper:hover { background: #f1f5f9; }
.image-summary-paper span { overflow-wrap: anywhere; }
.image-summary-paper small { flex-shrink: 0; color: #64748b; }
</style>
