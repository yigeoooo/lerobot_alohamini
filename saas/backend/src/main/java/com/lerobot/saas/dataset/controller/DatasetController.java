package com.lerobot.saas.dataset.controller;

import com.lerobot.saas.common.api.ApiResponse;
import com.lerobot.saas.dataset.dto.DatasetRenameRequest;
import com.lerobot.saas.dataset.service.DatasetService;
import com.lerobot.saas.dataset.vo.DatasetVO;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/datasets")
public class DatasetController {

    private final DatasetService datasetService;

    public DatasetController(DatasetService datasetService) {
        this.datasetService = datasetService;
    }

    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<DatasetVO> upload(@RequestParam(required = false) String datasetName,
                                         @RequestParam("files") List<MultipartFile> files,
                                         @RequestParam(required = false) List<String> relativePaths) {
        return ApiResponse.success("数据集上传成功", datasetService.uploadDataset(datasetName, files, relativePaths));
    }

    @GetMapping("/mine")
    public ApiResponse<List<DatasetVO>> mine() {
        return ApiResponse.success(datasetService.listCurrentUserDatasets());
    }

    @PutMapping("/{datasetId}/name")
    public ApiResponse<Void> rename(@PathVariable String datasetId,
                                    @Valid @RequestBody DatasetRenameRequest request) {
        datasetService.renameDataset(datasetId, request);
        return ApiResponse.success("数据集名称修改成功", null);
    }

    @DeleteMapping("/{datasetId}")
    public ApiResponse<Void> delete(@PathVariable String datasetId) {
        datasetService.deleteDataset(datasetId);
        return ApiResponse.success("数据集删除成功", null);
    }
}
