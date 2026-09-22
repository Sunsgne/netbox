# ZENLENET 运营台

尊领日常用得到的一块：客户、订单、IP 资源、出账、专线，以及割接和维护通知。

NetBox 里保留的是 IPAM 这一层（地址、前缀、节点、租户）。Odoo 里保留的是客户、订单和发票。割接和维护走一条 Jira 式状态流，通知正文用现有邮件模板生成。机柜、无线、制造、网站、完整会计科目、库存和固定资产没有放进来。

台账 Excel 含有登录信息，不要放进 git。导入时会丢掉密码样式的单元格。

## 本地

```bash
cd zenlenet-ops
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ADMIN_PASSWORD=choose-one
uvicorn app.main:app --reload
```

导入：

```bash
python -m app.importer \
  --ip "/path/IP Resources.xlsx" \
  --company "/path/ZENLENET PTE. LTD.xlsx" \
  --ipv6 "/path/IPV6 Resources.xlsx"
```

重新导入会重建客户、地址、订单、专线和账单，管理员账号和价目保留。

## 部署

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec ops python -m app.importer --ip /data/ip.xlsx --company /data/company.xlsx --ipv6 /data/ipv6.xlsx
```

演示价目不是合同价。账单页可以改单价，已生成的账单不会跟着变。
