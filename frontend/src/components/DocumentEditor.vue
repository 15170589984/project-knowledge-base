<script setup>
import { reactive, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import { NButton, NInput, NModal, NSelect, useMessage } from 'naive-ui'
import { Link2, List, ListOrdered, Quote, Save as SaveIcon, Undo2, Redo2, X } from 'lucide-vue-next'
import { api } from '../api'

const props = defineProps({
  show: Boolean,
  entry: { type: Object, default: null },
  projects: { type: Array, required: true },
  categories: { type: Array, required: true },
  environments: { type: Array, required: true },
  initialProjectId: { type: Number, default: 0 },
  initialCategoryId: { type: Number, default: 0 },
})
const emit = defineEmits(['close', 'saved'])
const message = useMessage()
const saving = ref(false)
const loading = ref(false)
const error = ref('')
const form = reactive({ project_id: null, category_id: null, title: '', environment: '', content: '' })
const active = ref({})

const editor = useEditor({
  content: '',
  extensions: [StarterKit.configure({ heading: { levels: [1, 2, 3] }, link: { openOnClick: false, autolink: true } })],
  editorProps: { attributes: { class: 'rich-editor-content' } },
})

const projectOptions = () => props.projects.filter((item) => item.is_owner).map((item) => ({ label: item.name, value: item.id }))
const categoryOptions = () => props.categories.map((item) => ({ label: item.name, value: item.id }))
const environmentOptions = () => {
  const options = [...props.environments]
  const previous = props.entry?.environment
  if (previous && !options.some((option) => option.value === previous)) {
    options.push({ value: previous, label: previous + '（旧环境）' })
  }
  return options
}

watch(
  () => [props.show, props.entry?.id, editor.value],
  async () => {
    if (!props.show || !editor.value) return
    form.project_id = props.entry?.project_id || props.initialProjectId || props.projects.find((item) => item.is_owner)?.id || null
    form.category_id = props.entry?.category_id || props.initialCategoryId || props.categories[0]?.id || null
    form.title = props.entry?.title || ''
    form.environment = props.entry?.environment || null
    form.content = props.entry?.content || ''
    error.value = ''
    let body = props.entry?.body
    if (props.entry && !body) {
      loading.value = true
      try {
        body = (await api('/entries/' + props.entry.id)).body
      } catch (cause) {
        error.value = cause.message
      } finally {
        loading.value = false
      }
    }
    editor.value.commands.setContent(body || '', { emitUpdate: false })
    refreshActive()
  },
  { immediate: true },
)

watch(editor, (instance) => {
  if (!instance) return
  instance.on('transaction', refreshActive)
  instance.on('selectionUpdate', refreshActive)
  refreshActive()
})

function refreshActive() {
  const instance = editor.value
  if (!instance) return
  active.value = {
    bold: instance.isActive('bold'),
    italic: instance.isActive('italic'),
    underline: instance.isActive('underline'),
    strike: instance.isActive('strike'),
    h1: instance.isActive('heading', { level: 1 }),
    h2: instance.isActive('heading', { level: 2 }),
    h3: instance.isActive('heading', { level: 3 }),
    bullet: instance.isActive('bulletList'),
    ordered: instance.isActive('orderedList'),
    quote: instance.isActive('blockquote'),
    code: instance.isActive('codeBlock'),
    link: instance.isActive('link'),
  }
}

function run(name, ...args) {
  editor.value?.chain().focus()[name](...args).run()
}

function setLink() {
  const instance = editor.value
  if (!instance) return
  const previous = instance.getAttributes('link').href || ''
  const href = window.prompt('请输入链接地址（http:// 或 https://）', previous || 'https://')
  if (href === null) return
  if (!href.trim()) {
    instance.chain().focus().extendMarkRange('link').unsetLink().run()
    return
  }
  if (!/^https?:\/\//i.test(href.trim())) {
    message.error('链接需以 http:// 或 https:// 开头')
    return
  }
  instance.chain().focus().extendMarkRange('link').setLink({ href: href.trim() }).run()
}

async function save() {
  error.value = ''
  if (!form.project_id || !form.category_id || !form.title.trim()) {
    error.value = '请选择项目、分类并填写文档名称'
    return
  }
  const html = editor.value?.getHTML() || ''
  if (!editor.value?.getText().trim()) {
    error.value = '文档内容不能为空'
    return
  }
  if (html.length > 200000) {
    error.value = '文档内容过长（最多 200000 字符）'
    return
  }
  const body = {
    title: form.title.trim(),
    environment: form.environment || null,
    content: form.content || null,
    body: html,
  }
  if (!props.entry) {
    body.project_id = form.project_id
    body.category_id = form.category_id
    body.kind = 'document'
  }
  saving.value = true
  try {
    const result = await api(props.entry ? '/entries/' + props.entry.id : '/entries', {
      method: props.entry ? 'PATCH' : 'POST',
      body,
    })
    message.success(props.entry ? '文档已更新' : '文档已创建')
    emit('saved', result)
    emit('close')
  } catch (cause) {
    error.value = cause.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <n-modal :show="show" preset="card" class="doc-editor-modal" :title="entry ? '编辑文档' : '新建文档'" :mask-closable="false" @close="emit('close')">
    <div class="form-grid">
      <div class="form-row two-columns">
        <div>
          <label class="field-label">所属项目</label>
          <n-select v-model:value="form.project_id" :options="projectOptions()" placeholder="选择项目" :disabled="!!entry" />
        </div>
        <div>
          <label class="field-label">分类</label>
          <n-select v-model:value="form.category_id" :options="categoryOptions()" placeholder="选择分类" :disabled="!!entry" />
        </div>
      </div>
      <div class="form-row two-columns">
        <div>
          <label class="field-label">文档名称 <span class="required">*</span></label>
          <n-input v-model:value="form.title" maxlength="160" placeholder="例如：接口对接说明" />
        </div>
        <div>
          <label class="field-label">环境</label>
          <n-select v-model:value="form.environment" :options="environmentOptions()" placeholder="不区分环境" clearable />
        </div>
      </div>
      <div class="form-row">
        <label class="field-label">备注</label>
        <n-input v-model:value="form.content" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="补充说明" />
      </div>
      <div class="rich-editor">
        <div class="rich-toolbar">
          <button type="button" class="rich-tool" :class="{ active: active.bold }" title="加粗" @click="run('toggleBold')"><strong>B</strong></button>
          <button type="button" class="rich-tool" :class="{ active: active.italic }" title="斜体" @click="run('toggleItalic')"><em>I</em></button>
          <button type="button" class="rich-tool" :class="{ active: active.underline }" title="下划线" @click="run('toggleUnderline')"><u>U</u></button>
          <button type="button" class="rich-tool" :class="{ active: active.strike }" title="删除线" @click="run('toggleStrike')"><span style="text-decoration: line-through">S</span></button>
          <span class="rich-tool-divider"></span>
          <button type="button" class="rich-tool" :class="{ active: active.h1 }" title="一级标题" @click="run('toggleHeading', { level: 1 })">H1</button>
          <button type="button" class="rich-tool" :class="{ active: active.h2 }" title="二级标题" @click="run('toggleHeading', { level: 2 })">H2</button>
          <button type="button" class="rich-tool" :class="{ active: active.h3 }" title="三级标题" @click="run('toggleHeading', { level: 3 })">H3</button>
          <span class="rich-tool-divider"></span>
          <button type="button" class="rich-tool" :class="{ active: active.bullet }" title="无序列表" @click="run('toggleBulletList')"><list :size="15" /></button>
          <button type="button" class="rich-tool" :class="{ active: active.ordered }" title="有序列表" @click="run('toggleOrderedList')"><list-ordered :size="15" /></button>
          <button type="button" class="rich-tool" :class="{ active: active.quote }" title="引用" @click="run('toggleBlockquote')"><quote :size="15" /></button>
          <button type="button" class="rich-tool" :class="{ active: active.code }" title="代码块" @click="run('toggleCodeBlock')"><code>&lt;/&gt;</code></button>
          <button type="button" class="rich-tool" :class="{ active: active.link }" title="链接" @click="setLink"><link2 :size="15" /></button>
          <span class="rich-tool-divider"></span>
          <button type="button" class="rich-tool" title="撤销" :disabled="!editor?.can().undo()" @click="run('undo')"><undo2 :size="15" /></button>
          <button type="button" class="rich-tool" title="重做" :disabled="!editor?.can().redo()" @click="run('redo')"><redo2 :size="15" /></button>
        </div>
        <editor-content :editor="editor" />
      </div>
      <div v-if="error" class="form-error" role="alert">{{ error }}</div>
    </div>
    <template #footer>
      <div class="modal-actions">
        <n-button @click="emit('close')"><template #icon><x :size="16" /></template>取消</n-button>
        <n-button type="primary" :loading="saving" :disabled="loading" @click="save"><template #icon><save-icon :size="16" /></template>保存</n-button>
      </div>
    </template>
  </n-modal>
</template>
