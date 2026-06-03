package com.lerobot.saas.training.controller;

import com.lerobot.saas.common.api.ApiResponse;
import com.lerobot.saas.training.dto.TrainTaskCreateRequest;
import com.lerobot.saas.training.service.TrainTaskService;
import com.lerobot.saas.training.vo.SavedModelVO;
import com.lerobot.saas.training.vo.TrainTaskVO;
import jakarta.validation.Valid;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream;
import org.apache.commons.compress.compressors.gzip.GzipCompressorOutputStream;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api/training-tasks")
public class TrainTaskController {

    private final TrainTaskService trainTaskService;

    public TrainTaskController(TrainTaskService trainTaskService) {
        this.trainTaskService = trainTaskService;
    }

    @PostMapping
    public ApiResponse<TrainTaskVO> create(@Valid @RequestBody TrainTaskCreateRequest request) {
        return ApiResponse.success("训练任务已创建", trainTaskService.createTrainTask(request));
    }

    @GetMapping("/mine")
    public ApiResponse<List<TrainTaskVO>> mine() {
        return ApiResponse.success(trainTaskService.listCurrentUserTasks());
    }

    @GetMapping("/saved-models")
    public ApiResponse<List<SavedModelVO>> savedModels() {
        return ApiResponse.success(trainTaskService.listCurrentUserSavedModels());
    }

    @GetMapping("/saved-models/download")
    public ResponseEntity<StreamingResponseBody> downloadSavedModel(@RequestParam String name) {
        Path modelPath = trainTaskService.requireSavedModelDownloadPath(name);
        StreamingResponseBody body = outputStream -> writeTarGz(modelPath, outputStream);
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + archiveFileName(modelPath) + "\"")
                .body(body);
    }

    @GetMapping("/{taskId}/log")
    public ApiResponse<String> log(@PathVariable String taskId) {
        return ApiResponse.success(trainTaskService.getTaskLog(taskId));
    }

    @PutMapping("/{taskId}/stop")
    public ApiResponse<Void> stop(@PathVariable String taskId) {
        trainTaskService.stopTask(taskId);
        return ApiResponse.success("训练任务已中断", null);
    }

    @GetMapping("/{taskId}/download")
    public ResponseEntity<StreamingResponseBody> download(@PathVariable String taskId) {
        Path outputPath = trainTaskService.requireTaskDownloadPath(taskId);
        StreamingResponseBody body = outputStream -> writeTarGz(outputPath, outputStream);
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + archiveFileName(outputPath) + "\"")
                .body(body);
    }

    private void writeTarGz(Path sourceDir, OutputStream outputStream) throws IOException {
        try (GzipCompressorOutputStream gzipOutputStream = new GzipCompressorOutputStream(outputStream);
             TarArchiveOutputStream tarOutputStream = new TarArchiveOutputStream(gzipOutputStream)) {
            tarOutputStream.setLongFileMode(TarArchiveOutputStream.LONGFILE_POSIX);
            tarOutputStream.setBigNumberMode(TarArchiveOutputStream.BIGNUMBER_POSIX);
            try (var stream = Files.walk(sourceDir)) {
                for (Path path : stream.filter(Files::isRegularFile).toList()) {
                    addTarEntry(sourceDir, path, tarOutputStream);
                }
            }
            tarOutputStream.finish();
        }
    }

    private void addTarEntry(Path sourceDir, Path path, TarArchiveOutputStream tarOutputStream) throws IOException {
        String relativeName = sourceDir.relativize(path).toString().replace("\\", "/");
        String entryName = sourceDir.getFileName().toString() + "/" + relativeName;
        TarArchiveEntry entry = new TarArchiveEntry(path.toFile(), entryName);
        tarOutputStream.putArchiveEntry(entry);
        Files.copy(path, tarOutputStream);
        tarOutputStream.closeArchiveEntry();
    }

    private String archiveFileName(Path sourceDir) {
        String baseName = sourceDir.getFileName().toString().replaceAll("[\\\\/:*?\"<>|\\s]+", "_");
        if (baseName.isBlank()) {
            baseName = "model";
        }
        return baseName + ".tar.gz";
    }
}
