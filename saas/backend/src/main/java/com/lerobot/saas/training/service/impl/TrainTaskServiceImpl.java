package com.lerobot.saas.training.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lerobot.saas.common.api.ResultCode;
import com.lerobot.saas.common.context.UserContext;
import com.lerobot.saas.common.context.UserContextHolder;
import com.lerobot.saas.common.exception.BusinessException;
import com.lerobot.saas.common.properties.TrainingProperties;
import com.lerobot.saas.dataset.dao.DatasetDao;
import com.lerobot.saas.dataset.entity.SysDataset;
import com.lerobot.saas.model.dao.ModelDao;
import com.lerobot.saas.model.entity.SysModel;
import com.lerobot.saas.training.dao.TrainTaskDao;
import com.lerobot.saas.training.dto.TrainTaskCreateRequest;
import com.lerobot.saas.training.entity.SysTrainTask;
import com.lerobot.saas.training.service.TrainTaskService;
import com.lerobot.saas.training.vo.SavedModelVO;
import com.lerobot.saas.training.vo.TrainTaskVO;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import java.util.stream.Stream;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
public class TrainTaskServiceImpl implements TrainTaskService {

    private static final String STATUS_PENDING = "PENDING";
    private static final String STATUS_RUNNING = "RUNNING";
    private static final String STATUS_SUCCESS = "SUCCESS";
    private static final String STATUS_FAILED = "FAILED";
    private static final String STATUS_STOPPED = "STOPPED";

    private final TrainTaskDao trainTaskDao;
    private final DatasetDao datasetDao;
    private final ModelDao modelDao;
    private final TrainingProperties trainingProperties;
    private final Path modelStorageRoot;
    private final Path trainingWorkDir;

    public TrainTaskServiceImpl(TrainTaskDao trainTaskDao,
                                DatasetDao datasetDao,
                                ModelDao modelDao,
                                TrainingProperties trainingProperties) {
        this.trainTaskDao = trainTaskDao;
        this.datasetDao = datasetDao;
        this.modelDao = modelDao;
        this.trainingProperties = trainingProperties;
        this.modelStorageRoot = Paths.get(requireConfiguredText(trainingProperties.outputRoot(), "saas.training.output-root"))
                .toAbsolutePath()
                .normalize();
        this.trainingWorkDir = Paths.get(requireConfiguredText(trainingProperties.workDir(), "saas.training.work-dir"))
                .toAbsolutePath()
                .normalize();
        if (Files.notExists(this.trainingWorkDir) || !Files.isDirectory(this.trainingWorkDir)) {
            throw new IllegalStateException("训练工作目录不存在: " + this.trainingWorkDir);
        }
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public TrainTaskVO createTrainTask(TrainTaskCreateRequest request) {
        UserContext userContext = currentUserContext();
        SysDataset dataset = requireOwnedDataset(request.getDatasetId(), userContext);
        SysModel model = requireModel(request.getModelId());

        SysTrainTask task = new SysTrainTask();
        task.setTaskName(request.getTaskName().trim());
        task.setOrganizationId(userContext.getOrganizationId());
        task.setUserId(userContext.getUserId());
        task.setDatasetId(dataset.getId());
        task.setDatasetName(dataset.getDatasetName());
        task.setDatasetPath(dataset.getStoragePath());
        task.setModelId(model.getId());
        task.setModelCode(model.getModelCode());
        task.setModelName(model.getModelName());
        String outputDir = resolveGeneratedOutputDir(model, userContext);
        ensureOutputDirAvailable(outputDir);
        task.setOutputDir(outputDir);
        task.setPolicyRepoId(request.getPolicyRepoId().trim());
        task.setDevice(defaultText(request.getDevice(), "cuda"));
        task.setWandbEnable(Boolean.TRUE.equals(request.getWandbEnable()));
        task.setSteps(request.getSteps());
        task.setBatchSize(request.getBatchSize());
        task.setUseAmp(request.getUseAmp() == null || Boolean.TRUE.equals(request.getUseAmp()));
        task.setOptimizerType(defaultText(request.getOptimizerType(), "adamw"));
        task.setOptimizerLr(defaultText(request.getOptimizerLr(), "1e-5"));
        task.setOptimizerWeightDecay(defaultText(request.getOptimizerWeightDecay(), "0.0"));
        task.setOptimizerGradClipNorm(defaultText(request.getOptimizerGradClipNorm(), "10.0"));
        task.setLogFreq(defaultInteger(request.getLogFreq(), 100));
        task.setSaveFreq(defaultInteger(request.getSaveFreq(), 5000));
        task.setPolicyChunkSize(defaultInteger(request.getPolicyChunkSize(), 40));
        task.setPolicyActionSteps(defaultInteger(request.getPolicyActionSteps(), 40));
        task.setTaskStatus(STATUS_PENDING);
        task.setLogPath(resolveLogPath(userContext, request.getTaskName()).toString());
        task.setCommandText(buildCommand(task));
        trainTaskDao.insert(task);
        startTrainingAfterCommit(task.getId());
        return toVO(task);
    }

    @Override
    public List<TrainTaskVO> listCurrentUserTasks() {
        UserContext userContext = currentUserContext();
        return trainTaskDao.selectList(new LambdaQueryWrapper<SysTrainTask>()
                        .eq(SysTrainTask::getOrganizationId, userContext.getOrganizationId())
                        .eq(SysTrainTask::getUserId, userContext.getUserId())
                        .orderByDesc(SysTrainTask::getCreatedTime))
                .stream()
                .map(this::toVO)
                .toList();
    }

    @Override
    public String getTaskLog(String taskId) {
        SysTrainTask task = requireOwnedTask(taskId);
        Path logPath = Paths.get(task.getLogPath()).toAbsolutePath().normalize();
        if (Files.notExists(logPath)) {
            return "";
        }
        try {
            String content = Files.readString(logPath, StandardCharsets.UTF_8);
            int maxLength = 120_000;
            return content.length() > maxLength ? content.substring(content.length() - maxLength) : content;
        } catch (IOException e) {
            throw new BusinessException("读取训练日志失败");
        }
    }

    @Override
    public void stopTask(String taskId) {
        SysTrainTask task = requireOwnedTask(taskId);
        if (!STATUS_RUNNING.equals(task.getTaskStatus()) && !STATUS_PENDING.equals(task.getTaskStatus())) {
            throw new BusinessException("当前任务状态不支持中断");
        }
        Long processId = task.getProcessId();
        if (processId != null) {
            ProcessHandle.of(processId).ifPresent(handle -> {
                handle.descendants().forEach(ProcessHandle::destroyForcibly);
                handle.destroyForcibly();
            });
        }
        task.setTaskStatus(STATUS_STOPPED);
        task.setErrorMessage("用户手动中断训练");
        trainTaskDao.updateById(task);
    }

    @Override
    public List<SavedModelVO> listCurrentUserSavedModels() {
        Path userRoot = resolveUserModelRoot(currentUserContext());
        if (Files.notExists(userRoot)) {
            return List.of();
        }
        try (Stream<Path> stream = Files.list(userRoot)) {
            return stream
                    .filter(Files::isDirectory)
                    .filter(this::hasRegularFile)
                    .map(this::toSavedModelVO)
                    .sorted(Comparator.comparing(SavedModelVO::updatedTime, Comparator.nullsLast(Comparator.reverseOrder())))
                    .toList();
        } catch (IOException e) {
            throw new BusinessException("读取个人模型目录失败");
        }
    }

    @Override
    public Path requireTaskDownloadPath(String taskId) {
        SysTrainTask task = requireOwnedTask(taskId);
        if (!STATUS_SUCCESS.equals(task.getTaskStatus())) {
            throw new BusinessException("模型尚未训练完成");
        }
        Path outputPath = Paths.get(task.getOutputDir()).toAbsolutePath().normalize();
        if (!outputPath.startsWith(resolveUserModelRoot(currentUserContext()))) {
            throw new BusinessException("模型输出目录不合法");
        }
        if (Files.notExists(outputPath) || !Files.isDirectory(outputPath)) {
            throw new BusinessException("模型输出目录不存在");
        }
        return outputPath;
    }

    @Override
    public Path requireSavedModelDownloadPath(String modelName) {
        Path userRoot = resolveUserModelRoot(currentUserContext());
        String safeName = normalizeDirectChildName(modelName);
        Path modelPath = userRoot.resolve(safeName).toAbsolutePath().normalize();
        if (!modelPath.startsWith(userRoot)) {
            throw new BusinessException("模型目录不合法");
        }
        if (Files.notExists(modelPath) || !Files.isDirectory(modelPath)) {
            throw new BusinessException("模型目录不存在");
        }
        return modelPath;
    }

    private void startTraining(String taskId) {
        Thread thread = new Thread(() -> runTraining(taskId), "train-task-" + taskId);
        thread.setDaemon(true);
        thread.start();
    }

    private void startTrainingAfterCommit(String taskId) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            startTraining(taskId);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                startTraining(taskId);
            }
        });
    }

    private void runTraining(String taskId) {
        SysTrainTask task = trainTaskDao.selectById(taskId);
        if (task == null || STATUS_STOPPED.equals(task.getTaskStatus())) {
            return;
        }
        try {
            Path logPath = Paths.get(task.getLogPath()).toAbsolutePath().normalize();
            Path outputPath = Paths.get(task.getOutputDir()).toAbsolutePath().normalize();
            Files.createDirectories(logPath.getParent());
            ensureOutputDirAvailable(task.getOutputDir());
            if (outputPath.getParent() != null) {
                Files.createDirectories(outputPath.getParent());
            }
            appendLog(logPath, "$ cd " + trainingWorkDir + System.lineSeparator());
            appendLog(logPath, "$ " + task.getCommandText() + System.lineSeparator());

            SysTrainTask latestBeforeStart = trainTaskDao.selectById(taskId);
            if (latestBeforeStart == null || STATUS_STOPPED.equals(latestBeforeStart.getTaskStatus())) {
                return;
            }

            Process process = new ProcessBuilder("bash", "-lc", task.getCommandText())
                    .directory(trainingWorkDir.toFile())
                    .redirectErrorStream(true)
                    .redirectOutput(ProcessBuilder.Redirect.appendTo(logPath.toFile()))
                    .start();
            task.setProcessId(process.pid());
            task.setTaskStatus(STATUS_RUNNING);
            trainTaskDao.updateById(task);

            int exitCode = process.waitFor();
            SysTrainTask latest = trainTaskDao.selectById(taskId);
            if (latest == null || STATUS_STOPPED.equals(latest.getTaskStatus())) {
                return;
            }
            latest.setExitCode(exitCode);
            latest.setTaskStatus(exitCode == 0 ? STATUS_SUCCESS : STATUS_FAILED);
            latest.setErrorMessage(exitCode == 0 ? null : "训练命令退出码: " + exitCode);
            trainTaskDao.updateById(latest);
        } catch (Exception e) {
            SysTrainTask latest = trainTaskDao.selectById(taskId);
            if (latest != null && !STATUS_STOPPED.equals(latest.getTaskStatus())) {
                latest.setTaskStatus(STATUS_FAILED);
                latest.setErrorMessage(e.getMessage());
                trainTaskDao.updateById(latest);
            }
        }
    }

    private String buildCommand(SysTrainTask task) {
        String condaSh = defaultText(trainingProperties.condaSh(), "/home/yigeoooo/miniconda3/etc/profile.d/conda.sh");
        String condaEnv = defaultText(trainingProperties.condaEnv(), "lerobot_alohamini");
        return "source " + shellQuote(condaSh)
                + " && conda activate " + shellQuote(condaEnv)
                + " && lerobot-train"
                + " --dataset.repo_id=" + shellQuote(task.getDatasetPath())
                + " --policy.type=" + shellQuote(task.getModelCode())
                + " --output_dir=" + shellQuote(task.getOutputDir())
                + " --policy.device=" + shellQuote(task.getDevice())
                + " --wandb.enable=" + task.getWandbEnable()
                + " --steps=" + task.getSteps()
                + " --batch_size=" + task.getBatchSize()
                + " --policy.use_amp=" + task.getUseAmp()
                + " --optimizer.type=" + shellQuote(task.getOptimizerType())
                + " --optimizer.lr=" + shellQuote(task.getOptimizerLr())
                + " --optimizer.weight_decay=" + shellQuote(task.getOptimizerWeightDecay())
                + " --optimizer.grad_clip_norm=" + shellQuote(task.getOptimizerGradClipNorm())
                + " --policy.repo_id=" + shellQuote(task.getPolicyRepoId())
                + " --log_freq=" + task.getLogFreq()
                + " --save_freq=" + task.getSaveFreq()
                + " --policy.chunk_size=" + task.getPolicyChunkSize()
                + " --policy.n_action_steps=" + task.getPolicyActionSteps();
    }

    private SysDataset requireOwnedDataset(String datasetId, UserContext userContext) {
        SysDataset dataset = datasetDao.selectById(datasetId);
        if (dataset == null || !Objects.equals(dataset.getOrganizationId(), userContext.getOrganizationId())
                || !Objects.equals(dataset.getUserId(), userContext.getUserId())
                || !"SUCCESS".equals(dataset.getUploadStatus())) {
            throw new BusinessException("数据集不存在或不可用于训练");
        }
        return dataset;
    }

    private SysModel requireModel(String modelId) {
        SysModel model = modelDao.selectById(modelId);
        if (model == null) {
            throw new BusinessException("模型不存在");
        }
        return model;
    }

    private SysTrainTask requireOwnedTask(String taskId) {
        UserContext userContext = currentUserContext();
        SysTrainTask task = trainTaskDao.selectById(taskId);
        if (task == null || !Objects.equals(task.getOrganizationId(), userContext.getOrganizationId())
                || !Objects.equals(task.getUserId(), userContext.getUserId())) {
            throw new BusinessException("训练任务不存在");
        }
        return task;
    }

    private UserContext currentUserContext() {
        UserContext userContext = UserContextHolder.get();
        if (userContext == null) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        return userContext;
    }

    private Path resolveLogPath(UserContext userContext, String taskName) {
        Path root = Paths.get(defaultText(trainingProperties.logRoot(), "/home/yigeoooo/project/train-logs"));
        return root.resolve(userContext.getOrganizationId()).resolve(userContext.getUserId())
                .resolve(sanitizePathName(taskName) + "-" + System.currentTimeMillis() + ".log")
                .toAbsolutePath().normalize();
    }

    private String resolveGeneratedOutputDir(SysModel model, UserContext userContext) {
        String modelDirectoryName = sanitizePathName(model.getModelCode()) + "_" + System.currentTimeMillis();
        Path outputPath = resolveUserModelRoot(userContext).resolve(modelDirectoryName).toAbsolutePath().normalize();
        return toUnixPath(outputPath);
    }

    private void ensureOutputDirAvailable(String outputDir) {
        Path outputPath = Paths.get(outputDir).toAbsolutePath().normalize();
        if (Files.exists(outputPath)) {
            throw new BusinessException("输出目录已存在，请修改输出目录或删除旧目录: " + outputPath);
        }
    }

    private Path resolveUserModelRoot(UserContext userContext) {
        return modelStorageRoot
                .resolve(userContext.getOrganizationId())
                .resolve(userContext.getUserId())
                .toAbsolutePath()
                .normalize();
    }

    private boolean containsParentReference(String value) {
        return value.equals("..") || value.startsWith("../") || value.endsWith("/..") || value.contains("/../");
    }

    private boolean hasRegularFile(Path directory) {
        try (Stream<Path> walk = Files.walk(directory)) {
            return walk.anyMatch(Files::isRegularFile);
        } catch (IOException e) {
            return false;
        }
    }

    private SavedModelVO toSavedModelVO(Path modelDir) {
        return new SavedModelVO(
                modelDir.getFileName().toString(),
                toUnixPath(modelDir),
                directorySize(modelDir),
                latestModifiedTime(modelDir)
        );
    }

    private long directorySize(Path directory) {
        try (Stream<Path> walk = Files.walk(directory)) {
            return walk.filter(Files::isRegularFile).mapToLong(this::safeFileSize).sum();
        } catch (IOException e) {
            return 0L;
        }
    }

    private LocalDateTime latestModifiedTime(Path directory) {
        try (Stream<Path> walk = Files.walk(directory)) {
            Path newest = walk.max(Comparator.comparingLong(this::lastModifiedMillis)).orElse(directory);
            return LocalDateTime.ofInstant(Files.getLastModifiedTime(newest).toInstant(), ZoneId.systemDefault());
        } catch (IOException e) {
            return null;
        }
    }

    private long safeFileSize(Path path) {
        try {
            return Files.size(path);
        } catch (IOException e) {
            return 0L;
        }
    }

    private long lastModifiedMillis(Path path) {
        try {
            return Files.getLastModifiedTime(path).toMillis();
        } catch (IOException e) {
            return 0L;
        }
    }

    private String normalizeDirectChildName(String rawName) {
        String normalized = Objects.requireNonNullElse(rawName, "").trim().replace("\\", "/");
        if (!StringUtils.hasText(normalized) || normalized.contains("/") || containsParentReference(normalized)) {
            throw new BusinessException("模型目录名称不合法");
        }
        return normalized;
    }

    private String sanitizePathName(String rawName) {
        return Objects.requireNonNullElse(rawName, "")
                .trim()
                .replaceAll("[\\\\/:*?\"<>|]", "_")
                .replaceAll("\\s+", "_");
    }

    private String requireConfiguredText(String value, String propertyName) {
        if (!StringUtils.hasText(value)) {
            throw new IllegalStateException("请配置 " + propertyName);
        }
        return value.trim();
    }

    private String toUnixPath(Path path) {
        return path.toAbsolutePath().normalize().toString().replace("\\", "/");
    }

    private String defaultText(String value, String defaultValue) {
        return StringUtils.hasText(value) ? value.trim() : defaultValue;
    }

    private Integer defaultInteger(Integer value, Integer defaultValue) {
        return value == null ? defaultValue : value;
    }

    private String shellQuote(String value) {
        return "\"" + value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("$", "\\$")
                .replace("`", "\\`")
                + "\"";
    }

    private void appendLog(Path logPath, String text) throws IOException {
        Files.writeString(logPath, text, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    }

    private TrainTaskVO toVO(SysTrainTask task) {
        return new TrainTaskVO(
                task.getId(),
                task.getTaskName(),
                task.getDatasetName(),
                task.getDatasetPath(),
                task.getModelCode(),
                task.getModelName(),
                task.getOutputDir(),
                task.getPolicyRepoId(),
                task.getDevice(),
                task.getWandbEnable(),
                task.getSteps(),
                task.getBatchSize(),
                task.getUseAmp(),
                task.getOptimizerType(),
                task.getOptimizerLr(),
                task.getOptimizerWeightDecay(),
                task.getOptimizerGradClipNorm(),
                task.getLogFreq(),
                task.getSaveFreq(),
                task.getPolicyChunkSize(),
                task.getPolicyActionSteps(),
                task.getTaskStatus(),
                task.getProcessId(),
                task.getCommandText(),
                task.getLogPath(),
                task.getExitCode(),
                task.getErrorMessage(),
                task.getCreatedTime(),
                task.getUpdatedTime()
        );
    }
}
