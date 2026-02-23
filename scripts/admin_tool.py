#!/usr/bin/env python3
import os
import sys
import shutil
import sqlite3
import datetime
import tarfile
import inquirer
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "voicebox_local.db"
PROFILES_DIR = DATA_DIR / "profiles"

def get_db():
    if not DB_PATH.exists():
        print("错误: 数据库文件不存在，请先启动一次 Web 服务或执行迁移脚本！")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def list_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT 
            u.username, u.role, u.created_at,
            (SELECT COUNT(*) FROM profiles WHERE owner = u.username) as profile_count,
            (SELECT COUNT(*) FROM history WHERE username = u.username) as history_count
        FROM users u
        ORDER BY u.created_at DESC
    """)
    rows = c.fetchall()
    
    print("-" * 80)
    print(f"{'用户名':<20} | {'角色':<10} | {'私有音色数':<12} | {'生成历史数':<12} | {'创建时间'}")
    print("-" * 80)
    for r in rows:
        print(f"{r['username']:<20} | {r['role']:<10} | {r['profile_count']:<12} | {r['history_count']:<12} | {r['created_at']}")
    print("-" * 80)
    print(f"总计用户数: {len(rows)}\n")
    conn.close()

def list_profiles():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, owner, is_default, created_at FROM profiles ORDER BY created_at DESC")
    rows = c.fetchall()
    
    print("-" * 100)
    print(f"{'音色名称':<25} | {'归属者':<15} | {'公共默认':<8} | {'创建时间':<20} | {'ID'}")
    print("-" * 100)
    for r in rows:
        is_def = "是" if r["is_default"] == 1 else "否"
        
        # We need to manually count visual width if there are CJK characters.
        # But for simple formatting, we can just print as is and it might be slightly off.
        name_str = (r['name'][:22] + '...') if len(r['name']) > 25 else r['name']
        owner_str = (r['owner'][:12] + '...') if len(r['owner']) > 15 else r['owner']
        print(f"{name_str:<25} | {owner_str:<15} | {is_def:<8} | {r['created_at']:<20} | {r['id']}")
    print("-" * 100)
    print(f"总计收录音色数: {len(rows)}\n")
    conn.close()

def delete_user():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username FROM users ORDER BY username")
    users = [r["username"] for r in c.fetchall()]
    conn.close()
    
    if not users:
        print("当前没有任何用户。\n")
        return

    ans = inquirer.prompt([inquirer.List("target", message="请选择要灭杀的用户", choices=users)])
    if not ans: return
    username = ans["target"]

    if username == "admin123":
        print("错误: admin123 是内置最高超管，不可删除！\n")
        return
        
    confirm = input(f"警告: 你确定要抹除用户 '{username}' 以及其所有音色、音频录音吗? 此操作极其危险且不可逆！ (y/N): ")
    if confirm.lower() != 'y':
        print("已取消删除操作。\n")
        return
        
    conn = get_db()
    c = conn.cursor()
    # 物理删除所有私有音色文件夹
    c.execute("SELECT id FROM profiles WHERE owner=?", (username,))
    profile_rows = c.fetchall()
    deleted_p_count = 0
    for row in profile_rows:
        folder = PROFILES_DIR / row["id"]
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        deleted_p_count += 1
        
    c.execute("DELETE FROM profiles WHERE owner=?", (username,))
    c.execute("DELETE FROM history WHERE username=?", (username,))
    deleted_h_count = c.rowcount
    c.execute("DELETE FROM hidden_profiles WHERE username=?", (username,))
    c.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    
    print(f"✅ 抹杀成功！已清除用户 {username} 的 {deleted_p_count} 个私有音色，和 {deleted_h_count} 条生成记录。\n")

def set_role():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, role FROM users ORDER BY username")
    users = [f"{r['username']} (当前: {r['role']})" for r in c.fetchall()]
    conn.close()

    if not users: return
    
    ans1 = inquirer.prompt([inquirer.List("user", message="请选择操作对象", choices=users, carousel=True)])
    if not ans1: return
    target_user = ans1["user"].split(" ")[0]
    
    ans2 = inquirer.prompt([inquirer.List("role", message=f"设置 {target_user} 的全站权限", choices=["admin", "regular"])])
    if not ans2: return
    new_role = ans2["role"]

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET role=? WHERE username=?", (new_role, target_user))
    conn.commit()
    conn.close()
    print(f"✅ 成功将用户 '{target_user}' 的权限调整为: {new_role.upper()}\n")

def make_default():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, owner FROM profiles WHERE is_default=0 ORDER BY owner, created_at DESC")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        print("当前没有任何私有音色可以转正。\n")
        return
        
    choices = [f"[{r['owner']}] {r['name']}  ({r['id']})" for r in rows]
    ans = inquirer.prompt([inquirer.List("profile", message="请选择要强占转正的私有音色", choices=choices, carousel=True)])
    if not ans: return
    
    selection = ans["profile"]
    target_id = selection.split("(")[-1].strip(")")
    
    # 提取名字
    c = get_db().cursor()
    c.execute("SELECT name, owner FROM profiles WHERE id=?", (target_id,))
    row = c.fetchone()
    old_name = row["name"]
    owner = row["owner"]
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE profiles SET is_default=1, owner='system' WHERE id=?", (target_id,))
    conn.commit()
    conn.close()
    print(f"🚀 神级操作完成！用户 {owner} 炼制的私有音色 '{old_name}' 已成功被没收转正为【全站公共默认音色】！\n")

def backup_data():
    if not DATA_DIR.exists():
        print("[-] 没有找到 data 目录，无需备份。\n")
        return
    print("[*] 开始执行全站数据备份...")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"voicebox_data_backup_{timestamp}.tar.gz"
    backup_path = BASE_DIR / backup_filename
    try:
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(DATA_DIR, arcname=os.path.basename(DATA_DIR))
        print(f"✅ 备份成功！\n保存路径: {backup_path}\n大小: {os.path.getsize(backup_path) / (1024*1024):.2f} MB\n")
    except Exception as e:
        print(f"❌ 备份失败: {e}\n")

def main():
    print("=========================================")
    print("      🎙️ Voicebox Qwen 超管控制台      ")
    print("=========================================")
    while True:
        questions = [
            inquirer.List('action',
                          message="【管理大盘】请使用 ↑↓ 键选择操作并按回车执行",
                          choices=[
                              ('📋 列出所有站内访客/用户', 'list_users'),
                              ('🎵 列出所有音色及归属信息', 'list_profiles'),
                              ('👑 提拔/降级管理员权限', 'set_role'),
                              ('🌟 夺取私有音色变全局默认', 'make_default'),
                              ('💀 彻底销户并擦除所有资产', 'delete_user'),
                              ('📦 数据一键防灾热备份', 'backup'),
                              ('❌ 退出控制台', 'exit')
                          ],
                          carousel=True),
        ]
        
        try:
            answers = inquirer.prompt(questions)
            if not answers:
                break
                
            action = answers['action']
            if action == 'list_users':
                list_users()
            elif action == 'list_profiles':
                list_profiles()
            elif action == 'set_role':
                set_role()
            elif action == 'make_default':
                make_default()
            elif action == 'delete_user':
                delete_user()
            elif action == 'backup':
                backup_data()
            elif action == 'exit':
                print("👋 退出控制台工作站。\n")
                break
        except KeyboardInterrupt:
            print("\n👋 强制终止控制台。\n")
            break

if __name__ == "__main__":
    main()
