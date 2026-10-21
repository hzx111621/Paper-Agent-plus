<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { pushToast } from "../stores/notifications";

type Preset = { id: string; label: string; api_base: string; models: string[]; docs: string };
type Config = { backend: string; api_base: string; model: string; language: string };
type Payload = { config: Config; configured: boolean; presets: Preset[] };
const presets = ref<Preset[]>([]);
const draft = reactive({ backend: "", api_base: "", model: "", language: "中文", api_key: "" });
const configured = ref(false);
const saving = ref(false);
const loading = ref(true);
const errorMessage = ref("");
const preset = computed(() => presets.value.find((item) => item.id === draft.backend));

// API Key 输入框只用于提交新密钥，读取配置时后端不会返回已保存的密钥。
async function request(init?: RequestInit): Promise<Payload> {
  const response = await fetch("/api/settings/image-generation", { ...init, headers: { "Content-Type": "application/json" } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || "生图配置请求失败");
  return body as Payload;
}

onMounted(async () => {
  try {
    const payload = await request();
    presets.value = payload.presets;
    Object.assign(draft, payload.config);
    draft.language ||= "中文";
    configured.value = payload.configured;
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : "读取配置失败"; }
  finally { loading.value = false; }
});

function chooseService() {
  // 更换服务时清空旧密钥，防止误把一个平台的密钥发给另一个平台。
  draft.api_base = preset.value?.api_base || "";
  draft.model = preset.value?.models[0] || "";
  draft.api_key = "";
}

async function save() {
  saving.value = true;
  errorMessage.value = "";
  try {
    const payload = await request({ method: "PUT", body: JSON.stringify(draft) });
    configured.value = payload.configured;
    draft.api_key = "";
    pushToast({ tone: "success", title: "生图配置已保存", description: "可在论文结果或论文资料库中点击“一图总结”。" });
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : "保存失败"; }
  finally { saving.value = false; }
}
</script>

<template>
  <section class="panel-section">
    <div class="editor-head"><div><h2>生图模型配置 · 一图总结</h2><p>选择生图服务后会自动填入模型和地址，再填写自己的 API Key 并保存。用阅读模型提取论文视觉信息后，将调用这个生图模型生成海报。</p></div><span>{{ configured ? '已保存配置' : '待配置' }}</span></div>
    <p v-if="loading">正在读取配置…</p>
    <form v-else class="editor-card" @submit.prevent="save">
      <div class="form-grid">
        <label>生图服务<select v-model="draft.backend" class="field" required @change="chooseService"><option disabled value="">请选择服务</option><option v-for="item in presets" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
        <label>模型名称<input v-model="draft.model" class="field" list="image-model-candidates" placeholder="选择候选或填写模型 ID" required /><datalist id="image-model-candidates"><option v-for="model in preset?.models || []" :key="model" :value="model" /></datalist></label>
        <label>API 基础地址<input v-model="draft.api_base" class="field" placeholder="https://…/v1" required /></label>
        <label>API Key<input v-model="draft.api_key" class="field" type="password" autocomplete="new-password" :placeholder="configured ? '同一服务留空保留密钥；更换地址需重新填写' : '填写你自己的生图服务密钥'" /></label>
        <label>图片文字语言<input v-model="draft.language" class="field" placeholder="中文 / English" required /></label>
      </div>
      <p class="paper-meta">模型是否可用取决于你的账户权限。模型候选依据官方文档整理，可自行填写服务支持的模型名称。<a v-if="preset" :href="preset.docs" target="_blank" rel="noreferrer">查看接口文档</a></p>
      <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
      <button class="button primary" type="submit" :disabled="saving">{{ saving ? '正在保存…' : '保存生图配置' }}</button>
    </form>
  </section>
</template>
