/* Native WebView2 confirm() can clip its buttons inside a narrow widget. */
function confirmSchoolSubscription(result) {
    return new Promise(resolve => {
        const previousFocus = document.activeElement;
        const dialog = document.createElement('dialog');
        dialog.setAttribute('aria-label', '학교 특별시정 변경');
        dialog.style.cssText = 'box-sizing:border-box;width:440px;max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);padding:12px;border:1px solid #bbc9bf;border-radius:12px;background:#fff;color:#202624;font:14px/1.5 sans-serif;overflow:hidden;';
        const panel = document.createElement('div');
        panel.style.cssText = 'display:flex;flex-direction:column;gap:10px;max-height:calc(100vh - 42px);min-height:0;';
        const title = document.createElement('strong');
        title.textContent = '특별시정 변경';
        title.style.cssText = 'flex-shrink:0;font-size:16px;';
        const details = document.createElement('div');
        details.style.cssText = 'min-height:0;overflow:auto;overflow-wrap:anywhere;white-space:pre-wrap;';
        details.tabIndex = 0;
        details.textContent = `${result.school_name} 특별시정 변경이 있어요.\n\n${result.changes.join('\n')}\n\n받아와서 적용할까요? 나중에를 누르면 기존 시정을 유지해요.`;
        const actions = document.createElement('div');
        actions.style.cssText = 'display:flex;gap:8px;flex-shrink:0;';
        let settled = false;
        function finish(accepted) {
            if (settled) return;
            settled = true;
            dialog.close();
            dialog.remove();
            if (previousFocus && previousFocus.isConnected) previousFocus.focus();
            resolve(accepted);
        }
        for (const [label, accepted] of [['나중에', false], ['받아오기', true]]) {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = label;
            button.style.cssText = `flex:1;min-width:0;padding:8px 4px;border:1px solid #bbc9bf;border-radius:7px;font:600 14px sans-serif;cursor:pointer;background:${accepted?'#1b6749':'#fff'};color:${accepted?'#fff':'#202624'};`;
            button.addEventListener('click', () => finish(accepted));
            actions.append(button);
        }
        panel.append(title, details, actions);
        dialog.append(panel);
        dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); });
        dialog.addEventListener('close', () => finish(false));
        document.body.append(dialog);
        dialog.showModal();
        actions.firstElementChild.focus();
    });
}
