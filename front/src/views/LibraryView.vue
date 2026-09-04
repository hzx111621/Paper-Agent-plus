<script setup lang="ts">
import { Download, ExternalLink, Flag, Heart, LoaderCircle, Search, StickyNote } from "lucide-vue-next";
import { onMounted, ref } from "vue";

import { listLibrary, patchPaper } from "../api/library";
import { pushToast } from "../stores/notifications";
import type { PaperRecord } from "../types/sessions";

const papers = ref<PaperRecord[]>([]);
const query = ref("");
const tag = ref("");
const favoriteOnly = ref(false);
const loading = ref(false);
const page = ref(1);
const pages = ref(0);
const total = ref(0);
const selected = ref<PaperRecord | null>(null);

onMounted(() => void load());

async function load() {
  loading.value = true;
  try {
    const payload = await listLibrary({ query: query.value, tag: tag.value, favorite_only: favoriteOnly.value, page: page.value, page_size: 12, sort: "updated_at" });
    papers.value = payload.papers;
    pages.value = payload.pages;
    total.value = payload.total;
  } catch (error) { pushToast({ tone: "error", title: "加载论文库失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
  finally { loading.value = false; }
}

async function save(paper: PaperRecord, patch: Partial<PaperRecord>) {
  try { Object.assign(paper, (await patchPaper(paper.paperId, patch)).paper); }
  catch (error) { pushToast({ tone: "error", title: "保存论文笔记失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}
</script>

<template>
  <section class="page-shell library-shell">
    <header class="hero-card"><div class="hero-copy"><span class="eyebrow">Personal Library</span><h1>论文资料库</h1><p>收藏、标记重点、记录笔记，并在后续调研中复用已经读过的论文。</p></div><span class="library-total">{{ total }} 篇</span></header>
    <section class="library-toolbar"><label class="paper-search"><Search :size="15" /><input v-model="query" placeholder="搜索标题、作者、摘要" @keyup.enter="page = 1; load()" /></label><input v-model="tag" class="field" placeholder="标签" @keyup.enter="page = 1; load()" /><label class="check-label"><input v-model="favoriteOnly" type="checkbox" @change="page = 1; load()" />只看收藏</label><button class="button primary compact" type="button" @click="page = 1; load()">检索</button></section>
    <div v-if="loading" class="paper-results-empty"><LoaderCircle class="spinning" :size="18" />正在加载论文库…</div>
    <div v-else-if="!papers.length" class="paper-results-empty"><StickyNote :size="18" />还没有收藏论文</div>
    <section v-else class="library-list">
      <article v-for="paper in papers" :key="paper.paperId" class="library-item">
        <div class="paper-result-title-row"><a :href="paper.url || paper.pdf_url || '#'" target="_blank" rel="noreferrer"><h2>{{ paper.title }}</h2><ExternalLink :size="14" /></a><span>{{ paper.year || '年份未知' }}</span></div>
        <p class="paper-meta">{{ paper.authors.join('、') || '作者未知' }} · {{ paper.source || '来源未知' }}</p>
        <p class="paper-abstract">{{ paper.abstract || '暂无摘要' }}</p>
        <div class="paper-result-buttons"><button class="icon-button" type="button" @click="save(paper, { favorite: !paper.favorite })"><Heart :size="15" :fill="paper.favorite ? 'currentColor' : 'none'" /></button><button class="icon-button" type="button" @click="save(paper, { focused: !paper.focused })"><Flag :size="15" :fill="paper.focused ? 'currentColor' : 'none'" /></button><a v-if="paper.pdf_url || paper.url" class="button secondary compact" :href="paper.pdf_url || paper.url" download target="_blank" rel="noreferrer" title="只下载原文，不执行总结"><Download :size="14" />下载原文</a><button class="button secondary compact" type="button" @click="selected = paper">编辑笔记</button><span v-for="item in paper.tags" :key="item" class="tag-chip">{{ item }}</span></div>
      </article>
    </section>
    <div class="paper-pagination"><button class="button secondary compact" :disabled="page <= 1" @click="page -= 1; load()">上一页</button><span>第 {{ page }} / {{ pages || 1 }} 页</span><button class="button secondary compact" :disabled="page >= pages" @click="page += 1; load()">下一页</button></div>
    <Teleport to="body"><div v-if="selected" class="session-delete-dialog-backdrop" @click.self="selected = null"><section class="editor-card library-note-dialog"><div class="editor-head"><div><h3>论文笔记</h3><p>{{ selected.title }}</p></div><button class="button primary compact" @click="selected = null">完成</button></div><textarea v-model="selected.note" class="field textarea" rows="8" placeholder="记录你的阅读笔记、关键结论或后续问题" /><input :value="selected.tags.join(', ')" class="field" placeholder="标签，用逗号分隔" @change="save(selected, { tags: ($event.target as HTMLInputElement).value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })" /><button class="button primary" type="button" @click="save(selected, { note: selected.note }); selected = null">保存笔记</button></section></div></Teleport>
  </section>
</template>
