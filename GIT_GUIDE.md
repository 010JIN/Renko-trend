# Git 版本控制使用指南

## 📌 当前配置
- **用户名**: Jin
- **邮箱**: jlin010201@gmail.com
- **仓库位置**: /Users/mac/quant_project/砖型图趋势过滤系统

## 🚀 常用命令

### 1. 查看当前状态
```bash
git status
```
显示哪些文件被修改、新增或删除

### 2. 保存新版本（三步走）

#### 步骤1: 添加要保存的文件
```bash
# 添加所有修改的文件
git add -A

# 或者添加特定文件
git add live_simulation.py
git add config/config.yaml

# 或者添加某个目录
git add core/
```

#### 步骤2: 提交版本并写说明
```bash
git commit -m "修复：修正实时采集K线的API调用"
```

#### 步骤3: （可选）推送到远程仓库
```bash
git push origin main
```

### 3. 查看历史记录
```bash
# 查看简洁的提交历史
git log --oneline

# 查看详细的提交历史
git log

# 查看最近5次提交
git log -5 --oneline

# 查看某个文件的修改历史
git log live_simulation.py
```

### 4. 查看修改内容
```bash
# 查看还未添加的修改
git diff

# 查看已添加但未提交的修改
git diff --staged

# 查看某个文件的修改
git diff live_simulation.py
```

### 5. 回退到以前的版本
```bash
# 查看历史版本
git log --oneline

# 回退到某个版本（不删除之后的提交）
git checkout <commit-id> .

# 或者创建新分支查看旧版本
git checkout -b old-version <commit-id>

# 回到最新版本
git checkout main
```

### 6. 恢复误删的文件
```bash
# 恢复某个文件到最后一次提交的状态
git checkout -- live_simulation.py

# 恢复所有文件
git checkout -- .
```

### 7. 撤销操作
```bash
# 撤销最后一次提交（保留修改）
git reset --soft HEAD~1

# 撤销最后一次提交（不保留修改）
git reset --hard HEAD~1

# 撤销某个文件的修改（未添加到暂存区）
git checkout -- live_simulation.py
```

## 📝 提交信息规范

建议使用清晰的提交信息格式：

```bash
git commit -m "类型：简短描述"
```

**常用类型：**
- `新增`: 添加新功能
- `修复`: 修复bug
- `优化`: 代码优化或性能提升
- `重构`: 代码重构
- `文档`: 文档更新
- `测试`: 添加或修改测试
- `配置`: 修改配置文件

**示例：**
```bash
git commit -m "新增：添加15分钟K线聚合功能"
git commit -m "修复：解决API返回数据格式错误"
git commit -m "优化：提升砖型图构建性能"
git commit -m "重构：简化实时采集逻辑"
```

## 🌿 分支管理

### 创建分支（用于实验新功能）
```bash
# 创建并切换到新分支
git checkout -b feature-新功能名称

# 例如：测试1分钟K线采集
git checkout -b feature-1min-kline
```

### 切换分支
```bash
# 切换到主分支
git checkout main

# 切换到其他分支
git checkout feature-新功能名称
```

### 合并分支
```bash
# 先切换到主分支
git checkout main

# 合并其他分支
git merge feature-新功能名称
```

### 删除分支
```bash
# 删除已合并的分支
git branch -d feature-新功能名称

# 强制删除未合并的分支
git branch -D feature-新功能名称
```

## 💾 实际工作流示例

### 场景1: 日常修改代码
```bash
# 1. 修改文件后，查看状态
git status

# 2. 添加修改的文件
git add live_simulation.py config/config.yaml

# 3. 提交版本
git commit -m "优化：改进实时K线采集逻辑"

# 4. 查看历史
git log --oneline
```

### 场景2: 尝试新功能（使用分支）
```bash
# 1. 创建新分支
git checkout -b feature-test-strategy

# 2. 在新分支上修改代码
# ... 修改文件 ...

# 3. 提交修改
git add -A
git commit -m "新增：添加新的交易策略"

# 4. 如果满意，切换回主分支并合并
git checkout main
git merge feature-test-strategy

# 5. 如果不满意，直接切回主分支
git checkout main
# 新分支的修改不会影响主分支
```

### 场景3: 回退到昨天的版本
```bash
# 1. 查看历史记录
git log --oneline

# 2. 找到昨天的commit-id（例如：a1b2c3d）
# 3. 回退
git reset --hard a1b2c3d

# 或者只回退某个文件
git checkout a1b2c3d -- live_simulation.py
```

## 🔗 连接到GitHub/GitLab（可选）

### 连接到远程仓库
```bash
# 添加远程仓库
git remote add origin https://github.com/你的用户名/仓库名.git

# 推送到远程
git push -u origin main

# 以后推送只需
git push
```

### 从远程仓库拉取
```bash
# 拉取最新代码
git pull

# 或者
git fetch
git merge origin/main
```

## 📊 查看项目历史图
```bash
# 图形化查看分支历史
git log --graph --oneline --all

# 更详细的图形化历史
git log --graph --pretty=format:'%Cred%h%Creset -%C(yellow)%d%Creset %s %Cgreen(%cr) %C(bold blue)<%an>%Creset' --abbrev-commit
```

## ⚠️ 注意事项

1. **提交前先查看**: 用 `git status` 和 `git diff` 检查修改
2. **写清楚提交信息**: 方便以后查找和理解
3. **经常提交**: 每完成一个小功能就提交，不要积累太多修改
4. **不要提交敏感信息**: API密钥、密码等（已在.gitignore中配置）
5. **实验用分支**: 测试新功能时用分支，避免污染主代码

## 🎯 快速参考

| 操作 | 命令 |
|------|------|
| 查看状态 | `git status` |
| 添加所有修改 | `git add -A` |
| 提交版本 | `git commit -m "说明"` |
| 查看历史 | `git log --oneline` |
| 查看修改 | `git diff` |
| 创建分支 | `git checkout -b 分支名` |
| 切换分支 | `git checkout 分支名` |
| 回退版本 | `git reset --hard <commit-id>` |
| 恢复文件 | `git checkout -- 文件名` |

---

**第一个版本已保存！** ✅
提交ID: b4f89ec
提交信息: "初始提交：实时模拟交易系统（简化版，直接采集目标周期K线）"
