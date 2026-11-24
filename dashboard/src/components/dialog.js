let previousOverflow=''
const dialogs=[]
const selector='button,input,select,textarea,a[href],summary,[tabindex]'
function controls(element) {
  return [...element.querySelectorAll(selector)].filter(node=>
    !node.matches(':disabled') && node.tabIndex>=0 && !node.closest('[hidden],[inert]') &&
    getComputedStyle(node).visibility!=='hidden' && node.getClientRects().length)
}
function focusInside(element) {(controls(element)[0] || element).focus({preventScroll:true})}

export function mountDialog(element,onClose) {
  if(!element)return()=>{}
  const previousFocus=document.activeElement
  if(!dialogs.length){previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden'}
  dialogs.push(element)
  focusInside(element)
  const onFocus=event=>{
    if(dialogs.at(-1)===element && !element.contains(event.target))focusInside(element)
  }
  const onKey=event=>{
    if(dialogs.at(-1)!==element)return
    if(event.key==='Escape'){
      event.preventDefault();event.stopImmediatePropagation();onClose();return
    }
    if(event.key!=='Tab')return
    const nodes=controls(element),first=nodes[0],last=nodes.at(-1)
    if(!nodes.length){event.preventDefault();element.focus();return}
    if(event.shiftKey && (document.activeElement===first || document.activeElement===element || !element.contains(document.activeElement))){event.preventDefault();last.focus()}
    else if(!event.shiftKey && (document.activeElement===last || !element.contains(document.activeElement))){event.preventDefault();first.focus()}
  }
  document.addEventListener('focusin',onFocus)
  document.addEventListener('keydown',onKey)
  let mounted=true
  return()=>{
    if(!mounted)return
    mounted=false
    document.removeEventListener('focusin',onFocus);document.removeEventListener('keydown',onKey)
    const wasTop=dialogs.at(-1)===element
    const index=dialogs.indexOf(element)
    if(index>=0)dialogs.splice(index,1)
    if(!dialogs.length)document.body.style.overflow=previousOverflow
    if(wasTop){
      const remaining=dialogs.at(-1)
      if(previousFocus?.isConnected && (!remaining || remaining.contains(previousFocus)))previousFocus.focus({preventScroll:true})
      else if(remaining)focusInside(remaining)
    }
  }
}
