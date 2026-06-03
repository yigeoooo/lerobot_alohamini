# LeRobot AlohaMini 训练推理一体化平台

本项目是为 `lerobot_alohamini` 创建的训练推理一体化平台，目标是把训练、推理、权限、组织、用户和页面管理统一到一套可扩展的 SaaS 化系统中，便于后续持续接入新的训练页面、推理页面和业务模块。

当前平台采用前后端分离架构：
- 前端：Vue 3 + Vite + Element Plus
- 后端：Spring Boot 3 + MyBatis-Plus + MySQL + JWT

## 项目定位

平台围绕 `lerobot_alohamini` 的训练与推理场景建设，当前先完成基础底座能力：
- 本地账号登录
- 组织管理
- 用户管理
- 页面路由权限管理
- 组织与页面权限绑定
- 个人中心
- 图标配置管理支撑

后续新增训练页、推理页时，可以直接在前端录入页面标题、路由路径、组件路径和图标信息，再将页面权限授权给组织，登录后即可动态展示对应菜单和页面。

## 目录说明

- `saas/frontend`：前端工程
- `saas/backend`：后端工程

## 已实现基础能力

- `sys_user` 用户表，本地登录校验
- `sys_organization` 组织表
- `sys_route_permission` 页面路由权限表
- `sys_organization_route_permission` 组织页面权限关联表
- `sys_icon` 图标表
- 管理员拥有最大页面权限，可查看全部页面
- 普通用户按所属组织加载可见页面
- 组织、用户等业务删除默认采用逻辑删除
- 组织赋权采用“先物理删除原有关联，再重新新增”的方式
- 应用启动自动同步核心表结构并初始化默认数据


## 数据库与环境

后端区分本地开发环境与测试环境：

- 开发库：`lerobot_saas_dev`
- 测试库：`lerobot_saas_test`

对应配置文件：

- 开发环境：`saas/backend/src/main/resources/application-dev.yml`
- 测试环境：`saas/backend/src/main/resources/application-test.yml`

前端同样区分开发与测试环境：

- 开发环境变量：`saas/frontend/.env.development`
- 测试环境变量：`saas/frontend/.env.test`

当前默认存储路径：

- 开发环境：`/home/yigeoooo/project/lerobot_alohamini/saas/storage/dev`
- 测试环境：`/srv/lerobot/saas/storage/test`

## 数据库初始化

初始化脚本位置：`sql/init.sql`

脚本内容包括：
- 创建 `lerobot_saas_dev`
- 创建 `lerobot_saas_test`
- 创建核心业务表
- 初始化默认组织
- 初始化默认管理员
- 初始化图标数据、默认页面权限和默认组织权限关系

执行示例：

```bash
mysql -uroot -p < saas/sql/init.sql
```

## 启动方式

### 后端启动

开发环境：

```bash
cd saas/backend
mvn spring-boot:run -Dspring-boot.run.profiles=dev
```

测试环境：

```bash
cd saas/backend
mvn spring-boot:run -Dspring-boot.run.profiles=test
```

### 前端启动

先安装依赖：

```bash
cd saas/frontend
npm install
```

开发环境：

```bash
cd saas/frontend
npm run dev
```

测试环境：

```bash
cd saas/frontend
npm run dev:test
```

## 打包方式

前端开发环境打包：

```bash
cd saas/frontend
npm run build
```

前端测试环境打包：

```bash
cd saas/frontend
npm run build:test
```

后端打包：

```bash
cd saas/backend
mvn clean package -DskipTests
```

测试环境 Jar 运行：

```bash
cd saas/backend
java -jar target/saas-backend-0.0.1-SNAPSHOT.jar --spring.profiles.active=test
```

## 权限使用流程

1. 前端新增一个 Vue 页面并完成实际开发。
2. 以管理员身份进入“页面权限”页面，录入页面标题、前端路由、组件路径、图标等信息。
3. 进入“组织赋权”页面，把页面权限分配给目标组织。
4. 目标组织用户重新登录或刷新后，即可看到新页面。
5. 管理员由于拥有最大权限，会自动看到全部页面。

## 表设计约定

所有业务表统一包含以下基础字段：

- `id`
- `sort`
- `deleted`
- `created_time`
- `updated_time`

约定如下：

- `id` 使用 MyBatis-Plus 雪花算法
- `id` 存储类型为字符串
- 涉及删除的业务默认采用逻辑删除
- 如新增或变更表结构，需要同步更新数据库

## 相关说明文档

- 后端说明见 [backend/README.md](./backend/README.md)
- 前端说明见 [frontend/README.md](./frontend/README.md)
