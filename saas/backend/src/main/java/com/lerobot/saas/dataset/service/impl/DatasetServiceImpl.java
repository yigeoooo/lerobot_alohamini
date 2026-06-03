package com.lerobot.saas.dataset.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lerobot.saas.common.api.ResultCode;
import com.lerobot.saas.common.context.UserContext;
import com.lerobot.saas.common.context.UserContextHolder;
import com.lerobot.saas.common.exception.BusinessException;
import com.lerobot.saas.common.properties.StorageProperties;
import com.lerobot.saas.dataset.dao.DatasetDao;
import com.lerobot.saas.dataset.dto.DatasetRenameRequest;
import com.lerobot.saas.dataset.entity.SysDataset;
import com.lerobot.saas.dataset.service.DatasetService;
import com.lerobot.saas.dataset.vo.DatasetVO;
import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream;
import org.apache.commons.compress.compressors.gzip.GzipCompressorInputStream;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

@Slf4j
@Service
public class DatasetServiceImpl implements DatasetService {

    private static final String STATUS_PROCESSING = "PROCESSING";
    private static final String STATUS_SUCCESS = "SUCCESS";
    private static final String STATUS_FAILED = "FAILED";

    private final DatasetDao datasetDao;
    private final ObjectMapper objectMapper;
    private final Path datasetStorageRoot;

    public DatasetServiceImpl(DatasetDao datasetDao,
                              StorageProperties storageProperties,
                              ObjectMapper objectMapper) {
        this.datasetDao = datasetDao;
        this.objectMapper = objectMapper;
        this.datasetStorageRoot = Paths.get(storageProperties.datasetPath()).toAbsolutePath().normalize();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public DatasetVO uploadDataset(String datasetName, List<MultipartFile> files, List<String> relativePaths) {
        if (files == null || files.isEmpty()) {
            throw new BusinessException("请先选择要上传的数据集");
        }

        UserContext userContext = currentUserContext();
        String displayFileName = resolveDisplayFileName(files, relativePaths);
        String initialDatasetName = defaultDatasetName(datasetName, displayFileName);
        SysDataset dataset = new SysDataset();
        dataset.setDatasetName(initialDatasetName);
        dataset.setOrganizationId(userContext.getOrganizationId());
        dataset.setUserId(userContext.getUserId());
        dataset.setOriginalFileName(displayFileName);
        dataset.setStoragePath("PENDING");
        dataset.setUploadStatus(STATUS_PROCESSING);
        datasetDao.insert(dataset);

        Path userRoot = resolveUserRoot(userContext);
        Path tempDir = userRoot.resolve(".upload-" + dataset.getId()).toAbsolutePath().normalize();
        log.info("dataset upload root={}, tempDir={}", datasetStorageRoot, tempDir);

        try {
            Files.createDirectories(tempDir);
            materializeDataset(files, relativePaths, tempDir);

            Path datasetRoot = locateDatasetRoot(tempDir);
            DatasetMetadata metadata = parseMetadata(datasetRoot);
            String finalDatasetName = StringUtils.hasText(datasetName) ? sanitizeDatasetDirectoryName(datasetName) : metadata.datasetName();
            Path finalDatasetPath = moveDatasetToUserDirectory(datasetRoot, userRoot, finalDatasetName);

            dataset.setDatasetName(finalDatasetName);
            dataset.setStoragePath(toUnixPath(finalDatasetPath));
            dataset.setUploadStatus(STATUS_SUCCESS);
            dataset.setErrorMessage(null);
            dataset.setCodebaseVersion(metadata.codebaseVersion());
            dataset.setRobotType(metadata.robotType());
            dataset.setTotalEpisodes(metadata.totalEpisodes());
            dataset.setTotalFrames(metadata.totalFrames());
            dataset.setTotalTasks(metadata.totalTasks());
            dataset.setFps(metadata.fps());
            dataset.setDataFilesSizeMb(metadata.dataFilesSizeMb());
            dataset.setVideoFilesSizeMb(metadata.videoFilesSizeMb());
            dataset.setFeatureCount(metadata.featureCount());
            dataset.setCameraCount(metadata.cameraCount());
            dataset.setFeatureKeys(metadata.featureKeys());
            dataset.setCameraKeys(metadata.cameraKeys());
            dataset.setMetadataJson(metadata.metadataJson());
            datasetDao.updateById(dataset);
            cleanupQuietly(tempDir);
            return toVO(dataset);
        } catch (Exception ex) {
            dataset.setUploadStatus(STATUS_FAILED);
            dataset.setErrorMessage(truncateMessage(ex.getMessage()));
            datasetDao.updateById(dataset);
            cleanupQuietly(tempDir);
            throw new BusinessException("数据集上传失败：" + normalizeExceptionMessage(ex));
        }
    }

    @Override
    public List<DatasetVO> listCurrentUserDatasets() {
        UserContext userContext = currentUserContext();
        List<SysDataset> datasets = datasetDao.selectList(new LambdaQueryWrapper<SysDataset>()
                .eq(SysDataset::getOrganizationId, userContext.getOrganizationId())
                .eq(SysDataset::getUserId, userContext.getUserId())
                .eq(SysDataset::getUploadStatus, STATUS_SUCCESS)
                .orderByDesc(SysDataset::getCreatedTime));
        return datasets.stream().map(this::toVO).toList();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void renameDataset(String datasetId, DatasetRenameRequest request) {
        SysDataset dataset = requireOwnedDataset(datasetId);
        String newDatasetName = sanitizeDatasetDirectoryName(request.getDatasetName());
        Path currentPath = requireDatasetPath(dataset);
        Path targetPath = currentPath.resolveSibling(newDatasetName).toAbsolutePath().normalize();

        if (currentPath.equals(targetPath)) {
            dataset.setDatasetName(newDatasetName);
            datasetDao.updateById(dataset);
            return;
        }
        if (!targetPath.startsWith(resolveUserRoot(currentUserContext()))) {
            throw new BusinessException("目标路径不合法");
        }
        if (Files.exists(targetPath)) {
            throw new BusinessException("同名数据集已存在");
        }

        try {
            movePath(currentPath, targetPath);
        } catch (IOException ex) {
            throw new BusinessException("数据集重命名失败：" + normalizeExceptionMessage(ex));
        }
        dataset.setDatasetName(newDatasetName);
        dataset.setStoragePath(toUnixPath(targetPath));
        datasetDao.updateById(dataset);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteDataset(String datasetId) {
        SysDataset dataset = requireOwnedDataset(datasetId);
        Path currentPath = requireDatasetPath(dataset);
        cleanupQuietly(currentPath);
        datasetDao.deleteByIdPhysical(dataset.getId());
    }

    private UserContext currentUserContext() {
        UserContext userContext = UserContextHolder.get();
        if (userContext == null) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        return userContext;
    }

    private Path resolveUserRoot(UserContext userContext) {
        return datasetStorageRoot
                .resolve(userContext.getOrganizationId())
                .resolve(userContext.getUserId())
                .toAbsolutePath()
                .normalize();
    }

    private SysDataset requireOwnedDataset(String datasetId) {
        UserContext userContext = currentUserContext();
        SysDataset dataset = datasetDao.selectById(datasetId);
        if (dataset == null || !Objects.equals(dataset.getOrganizationId(), userContext.getOrganizationId())
                || !Objects.equals(dataset.getUserId(), userContext.getUserId())) {
            throw new BusinessException("数据集不存在");
        }
        return dataset;
    }

    private Path requireDatasetPath(SysDataset dataset) {
        if (!StringUtils.hasText(dataset.getStoragePath())) {
            throw new BusinessException("数据集路径不存在");
        }
        Path datasetPath = Paths.get(dataset.getStoragePath()).toAbsolutePath().normalize();
        if (!datasetPath.startsWith(datasetStorageRoot)) {
            throw new BusinessException("数据集路径不合法");
        }
        if (Files.notExists(datasetPath)) {
            throw new BusinessException("数据集目录不存在");
        }
        return datasetPath;
    }

    private String resolveDisplayFileName(List<MultipartFile> files, List<String> relativePaths) {
        if (isFolderUpload(relativePaths, files)) {
            String firstPath = relativePaths.get(0);
            String normalized = normalizeRelativePath(firstPath);
            int index = normalized.indexOf("/");
            return index > 0 ? normalized.substring(0, index) : normalized;
        }
        return normalizeOriginalFileName(files.get(0).getOriginalFilename());
    }

    private String defaultDatasetName(String datasetName, String displayFileName) {
        if (StringUtils.hasText(datasetName)) {
            return sanitizeDatasetDirectoryName(datasetName);
        }
        String lowerCaseName = displayFileName.toLowerCase(Locale.ROOT);
        if (lowerCaseName.endsWith(".tar.gz")) {
            return sanitizeDatasetDirectoryName(displayFileName.substring(0, displayFileName.length() - 7));
        }
        if (lowerCaseName.endsWith(".tgz") || lowerCaseName.endsWith(".zip")) {
            return sanitizeDatasetDirectoryName(displayFileName.substring(0, displayFileName.lastIndexOf(".")));
        }
        return sanitizeDatasetDirectoryName(displayFileName);
    }

    private String sanitizeDatasetDirectoryName(String rawName) {
        String normalized = Objects.requireNonNullElse(rawName, "").trim();
        normalized = normalized.replaceAll("[\\\\/:*?\"<>|]", "_");
        normalized = normalized.replaceAll("\\s+", " ");
        if (!StringUtils.hasText(normalized)) {
            throw new BusinessException("数据集名称不能为空");
        }
        return normalized;
    }

    private void materializeDataset(List<MultipartFile> files,
                                    List<String> relativePaths,
                                    Path tempDir) throws IOException {
        if (isFolderUpload(relativePaths, files)) {
            writeFolderUpload(files, relativePaths, tempDir);
            return;
        }
        if (files.size() != 1) {
            throw new IOException("压缩包上传一次只能提交一个文件");
        }
        MultipartFile file = files.get(0);
        String originalFileName = normalizeOriginalFileName(file.getOriginalFilename());
        Path archivePath = tempDir.resolve(originalFileName);
        try (InputStream inputStream = file.getInputStream()) {
            Files.copy(inputStream, archivePath, StandardCopyOption.REPLACE_EXISTING);
        }
        if (isTarGz(originalFileName)) {
            extractTarGzArchive(archivePath, tempDir);
        } else if (isZip(originalFileName)) {
            extractZipArchive(archivePath, tempDir);
        } else {
            throw new IOException("当前仅支持 tar.gz、tgz、zip 或文件夹上传");
        }
        Files.deleteIfExists(archivePath);
    }

    private boolean isFolderUpload(List<String> relativePaths, List<MultipartFile> files) {
        return relativePaths != null && !relativePaths.isEmpty() && relativePaths.size() == files.size();
    }

    private void writeFolderUpload(List<MultipartFile> files, List<String> relativePaths, Path tempDir) throws IOException {
        for (int i = 0; i < files.size(); i++) {
            MultipartFile file = files.get(i);
            String relativePath = normalizeRelativePath(relativePaths.get(i));
            Path targetPath = tempDir.resolve(relativePath).normalize();
            if (!targetPath.startsWith(tempDir)) {
                throw new IOException("文件夹上传包含非法路径: " + relativePath);
            }
            Path parent = targetPath.getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            try (InputStream inputStream = file.getInputStream()) {
                Files.copy(inputStream, targetPath, StandardCopyOption.REPLACE_EXISTING);
            }
        }
    }

    private String normalizeRelativePath(String relativePath) {
        String cleaned = StringUtils.cleanPath(Objects.requireNonNullElse(relativePath, ""));
        if (!StringUtils.hasText(cleaned) || cleaned.contains("..")) {
            throw new BusinessException("文件夹路径不合法");
        }
        return cleaned.replace("\\", "/");
    }

    private String normalizeOriginalFileName(String originalFileName) {
        String cleaned = StringUtils.cleanPath(Objects.requireNonNullElse(originalFileName, "dataset"));
        if (!StringUtils.hasText(cleaned) || cleaned.contains("..")) {
            throw new BusinessException("上传文件名不合法");
        }
        return cleaned;
    }

    private boolean isTarGz(String fileName) {
        String lowerCaseName = fileName.toLowerCase(Locale.ROOT);
        return lowerCaseName.endsWith(".tar.gz") || lowerCaseName.endsWith(".tgz");
    }

    private boolean isZip(String fileName) {
        return fileName.toLowerCase(Locale.ROOT).endsWith(".zip");
    }

    private void extractTarGzArchive(Path archivePath, Path targetDir) throws IOException {
        try (InputStream fileInputStream = Files.newInputStream(archivePath);
             InputStream gzipInputStream = new GzipCompressorInputStream(fileInputStream);
             TarArchiveInputStream tarInputStream = new TarArchiveInputStream(gzipInputStream)) {
            TarArchiveEntry entry;
            while ((entry = tarInputStream.getNextEntry()) != null) {
                writeArchiveEntry(targetDir, entry.getName(), entry.isDirectory(), tarInputStream);
            }
        }
    }

    private void extractZipArchive(Path archivePath, Path targetDir) throws IOException {
        try (InputStream fileInputStream = Files.newInputStream(archivePath);
             ZipInputStream zipInputStream = new ZipInputStream(fileInputStream)) {
            ZipEntry entry;
            while ((entry = zipInputStream.getNextEntry()) != null) {
                writeArchiveEntry(targetDir, entry.getName(), entry.isDirectory(), zipInputStream);
                zipInputStream.closeEntry();
            }
        }
    }

    private void writeArchiveEntry(Path targetDir,
                                   String entryName,
                                   boolean directory,
                                   InputStream inputStream) throws IOException {
        String normalizedName = normalizeRelativePath(entryName);
        Path targetPath = targetDir.resolve(normalizedName).normalize();
        if (!targetPath.startsWith(targetDir)) {
            throw new IOException("归档文件包含非法路径: " + entryName);
        }
        if (directory) {
            Files.createDirectories(targetPath);
            return;
        }
        Path parent = targetPath.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        Files.copy(inputStream, targetPath, StandardCopyOption.REPLACE_EXISTING);
    }

    private Path locateDatasetRoot(Path tempDir) throws IOException {
        Path directInfoPath = tempDir.resolve("meta").resolve("info.json");
        if (Files.exists(directInfoPath)) {
            return tempDir;
        }
        try (Stream<Path> stream = Files.walk(tempDir, 6)) {
            Path infoPath = stream
                    .filter(Files::isRegularFile)
                    .filter(path -> "info.json".equals(path.getFileName().toString()))
                    .filter(path -> path.getParent() != null && "meta".equals(path.getParent().getFileName().toString()))
                    .findFirst()
                    .orElseThrow(() -> new IOException("未在上传内容中找到 meta/info.json"));
            return infoPath.getParent().getParent();
        }
    }

    private Path moveDatasetToUserDirectory(Path datasetRoot, Path userRoot, String datasetName) throws IOException {
        Path source = datasetRoot.toAbsolutePath().normalize();
        Path target = userRoot.resolve(sanitizeDatasetDirectoryName(datasetName)).toAbsolutePath().normalize();
        if (!source.startsWith(userRoot) || !target.startsWith(userRoot)) {
            throw new IOException("数据集目录路径不合法");
        }
        if (Files.exists(target)) {
            throw new IOException("同名数据集已存在");
        }
        Files.createDirectories(userRoot);
        movePath(source, target);
        return target;
    }

    private void movePath(Path source, Path target) throws IOException {
        try {
            try {
                Files.move(source, target, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException ex) {
                Files.move(source, target);
            }
        } catch (IOException ex) {
            throw new IOException("目录操作失败: " + normalizeExceptionMessage(ex), ex);
        }
    }

    private DatasetMetadata parseMetadata(Path datasetRoot) throws IOException {
        Path infoPath = datasetRoot.resolve("meta").resolve("info.json");
        if (!Files.exists(infoPath)) {
            throw new IOException("数据集缺少 meta/info.json");
        }

        JsonNode infoNode = objectMapper.readTree(infoPath.toFile());
        JsonNode featuresNode = infoNode.path("features");
        List<String> featureKeys = new ArrayList<>();
        List<String> cameraKeys = new ArrayList<>();

        if (featuresNode.isObject()) {
            featuresNode.fieldNames().forEachRemaining(featureName -> {
                featureKeys.add(featureName);
                JsonNode featureNode = featuresNode.path(featureName);
                String dtype = featureNode.path("dtype").asText("");
                if ("video".equalsIgnoreCase(dtype) || featureName.startsWith("observation.images.")) {
                    cameraKeys.add(featureName);
                }
            });
        }

        return new DatasetMetadata(
                sanitizeDatasetDirectoryName(datasetRoot.getFileName().toString()),
                nullableText(infoNode.get("codebase_version")),
                nullableText(infoNode.get("robot_type")),
                nullableInteger(infoNode.get("total_episodes")),
                nullableLong(infoNode.get("total_frames")),
                nullableInteger(infoNode.get("total_tasks")),
                nullableInteger(infoNode.get("fps")),
                nullableDecimal(infoNode.get("data_files_size_in_mb")),
                nullableDecimal(infoNode.get("video_files_size_in_mb")),
                featureKeys.size(),
                cameraKeys.size(),
                String.join(",", featureKeys),
                String.join(",", cameraKeys),
                objectMapper.writeValueAsString(infoNode)
        );
    }

    private String nullableText(JsonNode node) {
        return node == null || node.isNull() ? null : node.asText();
    }

    private Integer nullableInteger(JsonNode node) {
        return node == null || node.isNull() ? null : node.asInt();
    }

    private Long nullableLong(JsonNode node) {
        return node == null || node.isNull() ? null : node.asLong();
    }

    private BigDecimal nullableDecimal(JsonNode node) {
        return node == null || node.isNull() ? null : node.decimalValue();
    }

    private String toUnixPath(Path path) {
        return path.toAbsolutePath().normalize().toString().replace("\\", "/");
    }

    private void cleanupQuietly(Path path) {
        if (path == null || Files.notExists(path)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(path)) {
            walk.sorted(Comparator.reverseOrder()).forEach(item -> {
                try {
                    Files.deleteIfExists(item);
                } catch (IOException ignored) {
                }
            });
        } catch (IOException ignored) {
        }
    }

    private String truncateMessage(String message) {
        if (!StringUtils.hasText(message)) {
            return null;
        }
        return message.length() > 500 ? message.substring(0, 500) : message;
    }

    private String normalizeExceptionMessage(Exception ex) {
        String message = ex.getMessage();
        return StringUtils.hasText(message) ? message : "归档解析异常";
    }

    private DatasetVO toVO(SysDataset dataset) {
        return new DatasetVO(
                dataset.getId(),
                dataset.getDatasetName(),
                dataset.getOrganizationId(),
                dataset.getUserId(),
                dataset.getOriginalFileName(),
                dataset.getStoragePath(),
                dataset.getUploadStatus(),
                dataset.getErrorMessage(),
                dataset.getCodebaseVersion(),
                dataset.getRobotType(),
                dataset.getTotalEpisodes(),
                dataset.getTotalFrames(),
                dataset.getTotalTasks(),
                dataset.getFps(),
                dataset.getDataFilesSizeMb(),
                dataset.getVideoFilesSizeMb(),
                dataset.getFeatureCount(),
                dataset.getCameraCount(),
                dataset.getFeatureKeys(),
                dataset.getCameraKeys(),
                dataset.getMetadataJson(),
                dataset.getCreatedTime()
        );
    }

    private record DatasetMetadata(
            String datasetName,
            String codebaseVersion,
            String robotType,
            Integer totalEpisodes,
            Long totalFrames,
            Integer totalTasks,
            Integer fps,
            BigDecimal dataFilesSizeMb,
            BigDecimal videoFilesSizeMb,
            Integer featureCount,
            Integer cameraCount,
            String featureKeys,
            String cameraKeys,
            String metadataJson
    ) {
    }
}
