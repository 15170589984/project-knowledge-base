function copyWithTextarea(value) {
  const area = document.createElement('textarea')
  area.value = value
  area.setAttribute('readonly', '')
  area.style.cssText = 'position:fixed;top:0;left:0;width:200px;height:40px;padding:0;border:0;outline:0;box-shadow:none;background:transparent;opacity:0.01;font-size:12px'
  document.body.appendChild(area)
  area.focus({ preventScroll: true })
  area.select()
  area.setSelectionRange(0, value.length)
  try {
    return document.execCommand('copy')
  } finally {
    document.body.removeChild(area)
  }
}

function copyWithRange(value) {
  const holder = document.createElement('div')
  holder.contentEditable = 'true'
  holder.textContent = value
  holder.style.position = 'fixed'
  holder.style.top = '0'
  holder.style.left = '0'
  holder.style.whiteSpace = 'pre'
  holder.style.opacity = '0'
  document.body.appendChild(holder)
  const range = document.createRange()
  range.selectNodeContents(holder)
  const selection = window.getSelection()
  selection.removeAllRanges()
  selection.addRange(range)
  try {
    return document.execCommand('copy')
  } finally {
    selection.removeAllRanges()
    document.body.removeChild(holder)
  }
}

function showManualCopy(value) {
  const overlay = document.createElement('div')
  overlay.style.cssText = 'position:fixed;inset:0;z-index:30000;background:#00000055;display:flex;align-items:center;justify-content:center'
  const box = document.createElement('div')
  box.style.cssText = 'width:min(560px,92vw);background:#fff;border-radius:8px;padding:16px;box-shadow:0 10px 40px #00000033'
  const tip = document.createElement('div')
  tip.textContent = '浏览器阻止了自动复制：内容已全选，请按 Ctrl+C 复制，然后关闭窗口'
  tip.style.cssText = 'font-size:13px;line-height:1.5;color:#333;margin-bottom:10px'
  const area = document.createElement('textarea')
  area.value = value
  area.readOnly = true
  area.style.cssText = 'width:100%;height:170px;font-size:13px;line-height:1.5;padding:8px;border:1px solid #ccd5d0;border-radius:6px;resize:vertical'
  const close = document.createElement('button')
  close.textContent = '关闭'
  close.style.cssText = 'margin-top:10px;padding:6px 18px;font-size:13px;border:0;border-radius:6px;background:#16866b;color:#fff;cursor:pointer'
  close.onclick = () => overlay.remove()
  overlay.onclick = (event) => { if (event.target === overlay) overlay.remove() }
  box.append(tip, area, close)
  overlay.append(box)
  document.body.append(overlay)
  area.focus()
  area.select()
  area.setSelectionRange(0, value.length)
}

export async function copyText(text) {
  const value = String(text ?? '')
  if (!value) throw new Error('没有可复制的内容')
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return true
    } catch {
      // HTTP 等非安全上下文或权限被拒时退回传统方案
    }
  }
  if (copyWithTextarea(value) || copyWithRange(value)) return true
  showManualCopy(value)
  return false
}
