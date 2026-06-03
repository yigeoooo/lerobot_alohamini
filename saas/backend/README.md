# LeRobot AlohaMini SaaS 后端说明

`saas/backend` 是 `lerobot_alohamini` 训练推理一体化平台的后端服务，负责登录鉴权、组织权限、用户管理、页面权限管理以及基础数据初始化与表结构同步。

技术栈：
- Spring Boot 3
- Java 21
- MyBatis-Plus
- MySQL 8
- JWT

## 主要能力

- 本地账号密码登录
- JWT 鉴权拦截
- 统一返回结构
- 全局异常处理
- 自定义业务异常
- 组织 CRUD
- 用户 CRUD、密码重置、个人信息维护
- 页面路由权限 CRUD
- 组织页面赋权
- 图标列表查询
- 启动时同步核心表结构并初始化基础数据

## 代码分层约定

每个业务模块按以下方式组织：

- `controller`：接口层
- `service`：服务抽象接口
- `service/impl`：服务实现层
- `dao`：数据访问层
- `resources/mapper`：MyBatis XML SQL

公共能力放在其他基础包中，例如：

- 认证
- 异常处理
- 通用响应封装
- 雪花 ID
- 表结构同步

## 已落地的核心表

- `sys_user`
- `sys_organization`
- `sys_route_permission`
- `sys_organization_route_permission`
- `sys_icon`

表设计统一约定：

- 主键 `id` 为字符串类型雪花 ID
- 所有表包含 `sort`、`deleted`、`created_time`、`updated_time`
- 一般删除操作采用逻辑删除
- 组织赋权关系采用“先物理删除原数据，再重新写入”

## 环境配置

### 开发环境

配置文件：

- `src/main/resources/application-dev.yml`

默认数据库：

- `lerobot_saas_dev`

默认连接：

- 用户名：`root`
- 密码：`WJYy20011219`

### 测试环境

配置文件：

- `src/main/resources/application-test.yml`

默认数据库：

- `lerobot_saas_test`

测试环境默认存储目录：

- `/srv/lerobot/saas/storage/test`

## 启动项目

进入后端目录：

```bash
cd saas/backend
```

开发环境启动：

```bash
mvn spring-boot:run -Dspring-boot.run.profiles=dev
```

测试环境启动：

```bash
mvn spring-boot:run -Dspring-boot.run.profiles=test
```

## 打包与运行

打包：

```bash
cd saas/backend
mvn clean package -DskipTests
```

以测试环境运行 Jar：

```bash
cd saas/backend
java -jar target/saas-backend-0.0.1-SNAPSHOT.jar --spring.profiles.active=test
```

## 测试命令

```bash
cd saas/backend
mvn test
```

## 默认初始化数据

- 默认组织：`Aloha`
- 默认管理员：`王竞一`
- 登录邮箱：`632084210@qq.com`
- 初始密码：`Admin@123456`

## 开发注意事项

- 只要新增字段或修改表结构，就需要同步数据库。
- 当前项目通过启动阶段的表结构同步逻辑补齐基础表和字段，新增结构时需要继续维护同步逻辑。
- 页面权限是按组织控制的，管理员可查看全部页面。
- 组织被逻辑删除时，组织下用户也会联动逻辑删除。
- 用户被逻辑删除后，其相关业务信息也应按项目约定联动删除。
