# LeRobot AlohaMini SaaS 前端说明

`saas/frontend` 是 `lerobot_alohamini` 训练推理一体化平台的前端工程，负责登录页、主页、组织管理、用户管理、页面权限管理、组织赋权、个人中心等页面展示与交互。

技术栈：
- Vue 3
- Vite 5
- Element Plus
- Pinia
- Vue Router
- Axios

界面风格：
- 蓝白主题
- Element Plus 组件体系

## 当前页面能力

- 登录页
- 主页
- 组织管理
- 组织成员管理
- 页面权限管理
- 组织赋权
- 个人中心
- 用户管理中心

其中：

- 管理员可查看全部页面
- 普通用户只可查看所属组织已授权的页面
- 页面刷新后会重新补注册动态路由，避免白屏

## 环境说明

### 开发环境

配置文件：

- `.env.development`

当前配置：

- `VITE_API_BASE_URL=/api`
- `VITE_PROXY_TARGET=http://127.0.0.1:8080`
- `VITE_STORAGE_BASE_PATH=/home/yigeoooo/project/lerobot_alohamini/saas/storage/dev`

### 测试环境

配置文件：

- `.env.test`

当前配置：

- `VITE_API_BASE_URL=/api`
- `VITE_PROXY_TARGET=http://127.0.0.1:8080`
- `VITE_STORAGE_BASE_PATH=/srv/lerobot/saas/storage/test`

## 安装依赖

```bash
cd saas/frontend
npm install
```

## 启动项目

开发环境启动：

```bash
cd saas/frontend
npm run dev
```

测试环境启动：

```bash
cd saas/frontend
npm run dev:test
```

## 打包命令

开发环境打包：

```bash
cd saas/frontend
npm run build
```

测试环境打包：

```bash
cd saas/frontend
npm run build:test
```

本地预览打包结果：

```bash
cd saas/frontend
npm run preview
```

## 路由与权限机制

- 页面权限数据来源于后端 `sys_route_permission`
- 组织与页面关系来源于 `sys_organization_route_permission`
- 登录成功后，前端会根据当前用户的页面权限动态注册路由
- 管理员自动拥有全部页面权限
- 新页面开发完成后，可以在页面权限管理页录入标题、路由、组件路径、图标并保存到数据库
- 赋权后刷新页面，即可看到新菜单和对应页面

## 图标说明

- 页面图标与用户头像图标都基于数据库里的图标信息读取
- 图标名称来源于 Element Plus Icon 组件
- 前端通过图标接口查询可选图标列表，再供页面配置和用户头像选择使用

## 开发注意事项

- 开发新页面时，除了写 Vue 页面本身，还需要补充后端页面权限数据录入。
- 若页面要受权限控制，必须在页面权限管理中登记路由信息。
- 前后端环境是分开的，开发和测试的路径、存储目录、数据库目标都不能混用。
- 联调时不要使用 mock，应直接连接真实后端接口。
