# Fin-R1 快速验证指南（3分钟确认项目跑通）

## 🚀 快速验证（3分钟）

### Step 1: 检查服务状态（30秒）

```bash
cd /home/data/fin-r1-live

# 检查所有容器是否运行
docker-compose ps

# 预期看到:
# fin-r1-vllm      Up    端口8010
# finr1-datahub    Exit 0  (数据下载完成)
# finr1-middleware Up    端口8012
# fin-r1-webui     Up    端口8011
```

### Step 2: 一键测试（1分钟）

```bash
# 运行完整测试脚本
chmod +x test_end_to_end.sh
./test_end_to_end.sh

# 预期看到:
# ✅ 通过: 18项
# ⚠️  警告: 0-2项
# ❌ 失败: 0项
# 🎉 恭喜！所有核心测试通过！
```

### Step 3: 实际对话测试（90秒）

```bash
# 测试1: 基础对话
curl -X POST http://localhost:8012/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Fin-R1-Live",
    "messages": [{"role": "user", "content": "你好"}]
  }'
# 预期: 返回AI问候语

# 测试2: 带数据的对话（关键！）
curl -X POST http://localhost:8012/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Fin-R1-Live",
    "messages": [{"role": "user", "content": "分析000001的MACD"}]
  }'
# 预期: 返回包含"MACD"、"金叉/死叉"、"平安银行"的分析
```

## ✅ 项目完全跑通的标志

### 1. 数据下载完成
```bash
# 检查数据量
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT 
    (SELECT COUNT(*) FROM stocks) as 股票数,
    (SELECT COUNT(*) FROM stock_daily) as K线数,
    (SELECT MAX(trade_date) FROM stock_daily) as 最新日期;"

# 预期输出:
#  股票数 |  K线数  |  最新日期
# ---------+---------+------------
#   5234   | 1250000 | 2025-03-16
```

### 2. API全部可访问
```bash
# 健康检查
curl http://localhost:8012/health
# 预期: {"status": "healthy", ...}

# K线查询
curl http://localhost:8012/api/stock/000001/history?days=5
# 预期: 返回5天K线数据

# 技术指标
curl http://localhost:8012/api/stock/000001/indicators
# 预期: 返回MACD/BOLL/RSI/MA数据

# V1量化分析（核心！）
curl http://localhost:8012/api/stock/000001/v1-analysis | jq '.total_score'
# 预期: 返回评分数字(如82)
```

### 3. AI能使用数据生成回答
在Web UI中输入：
```
"分析000001的技术面和基本面"
```

**预期AI回答包含**:
- ✅ 股票名称"平安银行"
- ✅ K线走势描述
- ✅ MACD指标数值和信号
- ✅ 布林带位置
- ✅ PE、ROE等基本面数据

## 🎯 在Web UI中使用提示词

### 方式1: 直接在Web UI对话

1. 打开 http://你的IP:8011
2. 输入以下提示词开始对话：
```
你是一名专注A股市场的专业量化技术分析师。

请按照以下标准分析股票：
1. 技术面: 检查均线多头排列、MACD信号、布林带位置
2. 量能: 评估换手率和成交量趋势
3. 基本面: 查看PE、ROE、盈利增长
4. 板块: 判断行业排名和流动性

现在请分析000001平安银行。
```

### 方式2: 使用系统预置Prompt（推荐）

将 `prompt_v1_current.md` 内容配置到Web UI的**系统设置**中：

```bash
# 1. 读取V1版提示词
cat prompt_v1_current.md

# 2. 复制"一、角色与核心定位"到"七、使用示例"之间的内容

# 3. 在Web UI设置中:
#    - 点击左下角"设置"
#    - 找到"系统提示词(System Prompt)"
#    - 粘贴V1版提示词内容
#    - 保存
```

然后直接输入股票代码：
```
分析000001
```

AI会自动按照V1版标准给出量化评分和投资建议。

### 方式3: 使用API直接调用

```bash
# 批量选股（最实用！）
curl http://localhost:8012/api/screening/v1?min_score=75

# 返回符合条件的股票列表，包含:
# - 股票代码和名称
# - 综合评分
# - 各模块得分
# - 投资建议
```

## ⚡ 常见问题速查

### Q1: 数据Hub显示Exit 0是什么意思？
**A**: 正常！表示数据下载已完成，容器正常退出。如果需要增量更新，重启容器即可。

### Q2: Web UI能打开但AI回答很慢？
**A**: 
- 正常现象，首次对话vLLM需要预热
- 检查vLLM日志: `docker-compose logs fin-r1-vllm`
- 确保GPU正常工作: `nvidia-smi`

### Q3: AI回答"我没有数据"或"无法获取"？
**A**: 
- 检查数据是否下载完成: `./test_end_to_end.sh`
- 检查数据库连接: `curl http://localhost:8012/health`
- 确保股票代码正确（6位数字如000001）

### Q4: 提示词中的某些条件无法满足？
**A**: 这是正常的。当前V1版提示词移除了北向资金、主力资金、龙虎榜等暂不支持的数据。使用V1版即可获得完整体验。

### Q5: 如何确认数据真的被AI使用了？
**A**: 
1. 查看api-middleware日志: `docker-compose logs api-middleware | grep "意图分析"`
2. 检查返回的AI回答是否包含具体数值（如"MACD=0.15"）
3. 数值与直接查询API对比是否一致

## 📊 验证清单（全部勾选即跑通）

- [ ] Web UI可访问 (http://IP:8011)
- [ ] API中间层健康 (`/health`返回healthy)
- [ ] vLLM模型响应 (`/v1/models`返回模型列表)
- [ ] 数据库连接正常 (股票数>4000)
- [ ] K线数据完整 (>50万条)
- [ ] 财务数据可查 (PE/ROE数据返回)
- [ ] 技术指标计算正常 (MACD/BOLL/RSI返回)
- [ ] V1量化分析正常 (返回评分)
- [ ] 基础对话通顺 (AI能回复"你好")
- [ ] 带数据对话正常 (AI能分析000001)

## 🎉 完全跑通的最终验证

```bash
# 最终验证命令（全部通过即100%跑通）
echo "=== 最终验证 ==="
curl -s http://localhost:8012/health | jq -r '.status' && \
curl -s http://localhost:8010/v1/models | jq -r '.data[0].id' && \
curl -s http://localhost:8012/api/stock/000001/v1-analysis | jq -r '.total_score' && \
echo "✅ 项目完全跑通！"

# 预期输出:
# healthy
# Fin-R1-Live
# 82
# ✅ 项目完全跑通！
```

---

**结论**: 按照本指南验证，3分钟内可100%确认项目是否完全跑通，数据是否完整，AI模型是否能成功调用全部数据！
