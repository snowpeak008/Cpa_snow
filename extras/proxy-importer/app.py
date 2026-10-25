"""Chinese desktop importer. No network activity occurs until a button is clicked."""
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core import ROOT, RUNS, Binding, Controller, InputError, email_valid, normalize_proxy, parse_entries


class App:
    def __init__(self, root, controller=None):
        self.root = root
        self.controller = controller or Controller()
        self.queue = queue.Queue()
        self.busy = False
        self.preview_data = None
        self.bindings = None
        self.last_run = None
        self.revision = 0
        self.controls = []
        root.title('CPA 账号代理绑定工具')
        root.geometry('1130x' + str(min(980, root.winfo_screenheight()-100)))
        root.minsize(920, 740)
        root.configure(background='#f3f5f8')
        root.option_add('*Font', ('Microsoft YaHei UI', 10))
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background='#f3f5f8')
        style.configure('TLabel', background='#f3f5f8', foreground='#24354b')
        style.configure('TLabelframe', background='#f3f5f8')
        style.configure('TLabelframe.Label', background='#f3f5f8', foreground='#24354b')
        style.configure('TButton', padding=(12, 7))
        style.configure('Accent.TButton', background='#2762b2', foreground='white')
        style.map('Accent.TButton', background=[('disabled','#b7c5d6'),('active','#174d91')])
        style.configure('Treeview', rowheight=30, font=('Microsoft YaHei UI', 9))
        main = ttk.Frame(root, padding=20)
        main.pack(fill='both', expand=True)
        ttk.Label(main, text='账号代理 · 快速绑定', font=('Microsoft YaHei UI', 21, 'bold')).pack(anchor='w')
        ttk.Label(main, text='连接现有服务器 104.160.39.169  ·  只更新账号代理  ·  保留启用状态  ·  无需重启',
                  foreground='#536983').pack(anchor='w', pady=(4, 14))

        form = ttk.LabelFrame(main, text='单条填写 / 批量通用设置', padding=10)
        form.pack(fill='x')
        self.email = tk.StringVar()
        self.address = tk.StringVar()
        self.port = tk.StringVar(value='12323')
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.scheme = tk.StringVar(value='http')
        self.egress = tk.BooleanVar(value=False)
        fields = [('账号邮箱', self.email, 30), ('代理 IP / 主机', self.address, 23),
                  ('端口', self.port, 8), ('协议', self.scheme, 9)]
        for col, (label, var, width) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky='w', padx=4)
            if var is self.scheme:
                widget = ttk.Combobox(form, textvariable=var, values=('http','https','socks5','socks5h'), width=width, state='readonly')
            else:
                widget = ttk.Entry(form, textvariable=var, width=width)
            widget.grid(row=1, column=col, sticky='ew', padx=4, pady=(3, 7))
            self.controls.append(widget)
        ttk.Label(form, text='代理用户名（批量条目未填认证时共用）').grid(row=2, column=0, sticky='w', padx=4)
        ttk.Label(form, text='代理密码').grid(row=2, column=1, sticky='w', padx=4)
        user = ttk.Entry(form, textvariable=self.username)
        user.grid(row=3, column=0, sticky='ew', padx=4)
        pwd = ttk.Entry(form, textvariable=self.password, show='●')
        pwd.grid(row=3, column=1, sticky='ew', padx=4)
        self.controls.extend((user,pwd))
        add = ttk.Button(form, text='加入下方列表', command=self.add_one)
        add.grid(row=3, column=2, columnspan=2, sticky='ew', padx=4)
        self.controls.append(add)
        form.columnconfigure(0, weight=2)
        form.columnconfigure(1, weight=2)

        pastebox = ttk.LabelFrame(main, text='批量粘贴（按列表顺序执行）', padding=10)
        pastebox.pack(fill='x', pady=12)
        ttk.Label(pastebox, text='支持：邮箱一行，IP:端口:用户名:密码 下一行；也支持“邮箱 IP:端口”。空行会忽略。',
                  foreground='#536983').pack(anchor='w')
        self.text = tk.Text(pastebox, height=6, wrap='none', relief='solid', borderwidth=1,
                            font=('Consolas', 11), undo=False, background='white', foreground='#223147')
        self.text.pack(fill='x', pady=(6, 0))
        self.text.bind('<<Modified>>', self.on_text_modified)
        self.controls.append(self.text)
        for var in (self.email,self.address,self.port,self.username,self.password,self.scheme):
            var.trace_add('write', self.invalidate)
        bar = ttk.Frame(main)
        bar.pack(fill='x', pady=(0, 8))
        self.preview_button = ttk.Button(bar, text='1. 预览绑定', command=self.preview)
        self.preview_button.pack(side='left')
        self.bind_button = ttk.Button(bar, text='2. 确认绑定', style='Accent.TButton', command=self.bind, state='disabled')
        self.bind_button.pack(side='left', padx=8)
        clear = ttk.Button(bar, text='清空输入', command=self.clear)
        clear.pack(side='left')
        check = ttk.Checkbutton(bar, text='绑定后查询出口 IP（每账号一次）', variable=self.egress)
        check.pack(side='right')
        self.controls.extend((self.preview_button,self.bind_button,clear,check))

        table = ttk.Frame(main)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('email','state','old','new','check'), show='headings', height=6)
        for key, title, width in [('email','账号',245),('state','当前状态',90),('old','当前代理',200),('new','将绑定代理',200),('check','核对',165)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=65, stretch=True)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        footer = ttk.Frame(main)
        footer.pack(side='bottom', fill='x', before=table)
        ttk.Label(footer, text='“停用”表示 CPA 不调度该账号，不代表官方封禁。本工具不会启用或停用任何账号。',
                  foreground='#626f80').pack(anchor='w', pady=(5, 7))
        self.status = tk.StringVar(value='准备就绪：填写账号与代理，然后预览。')
        ttk.Label(footer, textvariable=self.status, wraplength=1040).pack(anchor='w', pady=(0, 5))
        self.log = tk.Text(footer, height=4, state='disabled', wrap='word', relief='flat',
                           background='#e9eef5', foreground='#34475d', font=('Microsoft YaHei UI', 9))
        self.log.pack(fill='x')
        bottom = ttk.Frame(footer)
        bottom.pack(fill='x', pady=(10, 0))
        self.rollback_button = ttk.Button(bottom, text='回退刚才这批', command=self.rollback_last, state='disabled')
        self.rollback_button.pack(side='left')
        history = ttk.Button(bottom, text='选择历史记录回退…', command=self.rollback_choose)
        history.pack(side='left', padx=8)
        folder = ttk.Button(bottom, text='打开记录目录', command=self.open_runs)
        folder.pack(side='right')
        self.controls.extend((self.rollback_button,history))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_timer = root.after(100, self.poll)

    def append_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def invalidate(self, *_):
        self.revision += 1
        self.preview_data = None
        self.bindings = None
        self.bind_button.configure(state='disabled')

    def on_text_modified(self, _event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.invalidate()

    def defaults(self):
        return {'username':self.username.get(), 'password':self.password.get(),
                'scheme':self.scheme.get(), 'port':self.port.get()}

    def add_one(self):
        try:
            email = self.email.get().strip()
            if not email_valid(email):
                raise InputError('请填写有效的账号邮箱。')
            proxy = normalize_proxy(self.address.get(), **self.defaults())
            current = self.text.get('1.0','end-1c')
            prefix = '\n' if current and not current.endswith('\n') else ''
            self.text.insert('end', prefix + email + ' ' + proxy + '\n')
            self.invalidate()
        except InputError as exc:
            messagebox.showerror('请检查输入', str(exc), parent=self.root)

    def clear(self):
        self.text.delete('1.0','end')
        for v in (self.email,self.address,self.username,self.password):
            v.set('')
        self.tree.delete(*self.tree.get_children())
        self.status.set('输入已清空；已保存的加密回退记录仍保留。')
        self.invalidate()

    def set_busy(self, busy):
        self.busy = busy
        for w in self.controls:
            w.configure(state='disabled' if busy else ('readonly' if isinstance(w, ttk.Combobox) else 'normal'))
        self.bind_button.configure(state='normal' if not busy and self.preview_data and self.preview_data.get('ok') else 'disabled')
        self.rollback_button.configure(state='normal' if not busy and self.last_run else 'disabled')

    def launch(self, action, callback):
        self.set_busy(True)
        def work():
            try:
                value = action()
                self.queue.put(('done',callback,value))
            except InputError as exc:
                self.queue.put(('error', str(exc)))
            except Exception as exc:
                self.queue.put(('error', '操作未完成（' + type(exc).__name__ + '）。请查看记录；未自动重试。'))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == 'progress':
                    self.status.set(item[1])
                    self.append_log(item[1])
                elif item[0] == 'done':
                    self.set_busy(False)
                    item[1](item[2])
                elif item[0] == 'error':
                    self.set_busy(False)
                    self.invalidate()
                    self.status.set(item[1])
                    self.append_log(item[1])
        except queue.Empty:
            pass
        self.poll_timer = self.root.after(100, self.poll)

    def preview(self):
        try:
            raw = self.text.get('1.0','end').strip()
            if not raw:
                if not email_valid(self.email.get().strip()):
                    raise InputError('请填写邮箱，或在下方粘贴批量内容。')
                bindings = [Binding(self.email.get().strip(), normalize_proxy(self.address.get(), **self.defaults()))]
            else:
                bindings = parse_entries(raw, **self.defaults())
        except InputError as exc:
            messagebox.showerror('请检查输入', str(exc), parent=self.root)
            return
        self.invalidate()
        self.tree.delete(*self.tree.get_children())
        self.status.set('正在读取 CPA 账号，只读预览…')
        revision = self.revision
        def done(result):
            if revision != self.revision:
                self.status.set('输入已变化，请重新预览。')
                return
            if 'rows' not in result:
                self.status.set(result.get('error','无法读取账号。'))
                return
            counts = {}
            targets = {b.email.casefold() for b in bindings}
            for r in result.get('inventory',[]):
                if r['email'].casefold() not in targets:
                    counts[r['endpoint']] = counts.get(r['endpoint'],0)+1
            for b in bindings:
                counts[b.endpoint] = counts.get(b.endpoint,0)+1
            for b,r in zip(bindings,result['rows']):
                a = r.get('account',{})
                check = '入口与其他账号相同' if counts[b.endpoint]>1 else '可绑定'
                self.tree.insert('', 'end', values=(b.email,
                    ('停用（不调度）' if a.get('disabled') else '启用') if r['ok'] else '未匹配',
                    a.get('endpoint','—'),b.endpoint,check if r['ok'] else r['error']))
                if not r['ok']:
                    self.append_log(b.email + '：' + r['error'])
            self.preview_data = result
            self.bindings = bindings
            self.set_busy(False)
            if result['ok']:
                self.status.set(f'已匹配 {len(bindings)} 个账号。确认上表后点击“确认绑定”；只更新代理。')
                self.bind_button.configure(text=f'2. 确认绑定 {len(bindings)} 个账号')
            else:
                self.status.set('有账号未匹配或重复，未执行任何修改；请检查邮箱。')
        self.launch(lambda:self.controller.preview(bindings),done)

    def bind(self):
        if not self.preview_data or not self.preview_data.get('ok') or not self.bindings:
            return
        bindings, preview, egress = self.bindings, self.preview_data, self.egress.get()
        self.status.set('正在加密保存原代理并逐个绑定…')
        def done(value):
            self.last_run, report = value
            results = {r['email'].casefold():r for r in report['results']}
            for item in self.tree.get_children():
                values = list(self.tree.item(item,'values'))
                row = results.get(values[0].casefold())
                if not row:
                    values[4] = '未执行'
                elif row['status']=='bound':
                    values[2] = row['endpoint']
                    values[4] = '已绑定' + (' / '+row['egress']['ip'] if row.get('egress',{}).get('ok') else '')
                else:
                    values[4] = '待核对 / 已停止'
                self.tree.item(item,values=values)
            self.invalidate()
            self.set_busy(False)
            successes = sum(r['status']=='bound' for r in report['results'])
            message = f'完成：{successes} 个账号已绑定。' if report['complete'] else f'已停止：{successes} 个账号已绑定，其余结果请查看记录。'
            message += ' 账号启用状态保持；可点击“回退刚才这批”。'
            self.status.set(message)
            self.append_log(message)
            self.append_log('记录目录：' + str(self.last_run))
        self.launch(lambda:self.controller.apply(bindings,preview,egress,
            lambda s:self.queue.put(('progress',s))),done)

    def rollback_last(self):
        if self.last_run:
            self.rollback(self.last_run)

    def rollback_choose(self):
        RUNS.mkdir(exist_ok=True)
        path = filedialog.askopenfilename(parent=self.root,title='选择要回退的一批记录中的 report.json',
            initialdir=RUNS,filetypes=[('绑定记录','report.json')])
        if path:
            self.rollback(Path(path).parent)

    def rollback(self, run):
        if not messagebox.askyesno('恢复原代理', '将恢复这批记录中已尝试修改账号的原代理。\n账号启用状态保持，不重启服务。\n\n是否回退？', parent=self.root):
            return
        self.invalidate()
        def done(result):
            self.status.set('原代理已恢复。' if result['complete'] else '回退已停止，存在冲突或连接问题；请查看回退记录。')
            self.append_log(self.status.get())
        self.launch(lambda:self.controller.restore(run,lambda s:self.queue.put(('progress',s))),done)

    def open_runs(self):
        RUNS.mkdir(exist_ok=True)
        os.startfile(str(RUNS))

    def close(self):
        if self.busy:
            messagebox.showinfo('操作进行中','请等待当前操作结束后关闭，以免留下结果不明的请求。',parent=self.root)
        else:
            self.root.after_cancel(self.poll_timer)
            self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
