package com.viva.standardizer_api;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.nio.file.*;
import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api")
public class ProcessController {

    private final Path base = Paths.get("data/uploads").toAbsolutePath();

    @Autowired
    private RestTemplate restTemplate; // defined in HttpConfig

    private final ObjectMapper om = new ObjectMapper();

    public ProcessController() throws Exception {
        Files.createDirectories(base);
    }

    @GetMapping("/download/{jobId}/{type}")
    public ResponseEntity<byte[]> download(@PathVariable String jobId, @PathVariable String type) {
        // Proxy to AI service: http://localhost:8001/download/{jobId}/{type}
        String url = "http://localhost:8001/download/" + jobId + "/" + type;

        var resp = restTemplate.getForEntity(url, byte[].class);

        MediaType ct = switch (type) {
            case "ideal" -> MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
            case "log" -> MediaType.TEXT_PLAIN;
            case "summary" -> MediaType.APPLICATION_JSON;
            default -> MediaType.APPLICATION_OCTET_STREAM;
        };

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(ct);
        String filename = switch (type) {
            case "ideal" -> "ideal_filled.xlsx";
            case "log" -> "transform_log.yaml";
            case "summary" -> "summary.json";
            default -> "download.bin";
        };
        headers.set(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=" + filename);

        return ResponseEntity.status(resp.getStatusCode()).headers(headers).body(resp.getBody());
    }

    @PostMapping(path = "/process", consumes = {"multipart/form-data"})
    public ResponseEntity<?> process(
            @RequestPart("ideal") MultipartFile ideal,
            @RequestPart("raw") MultipartFile raw,
            @RequestPart("instructions") MultipartFile instructions
    ) throws Exception {

        String jobId = UUID.randomUUID().toString();
        Path jobDir = base.resolve(jobId);
        Files.createDirectories(jobDir);

        // Save uploads locally (for audit/debug)
        save(ideal, jobDir.resolve("ideal_" + clean(ideal.getOriginalFilename())));
        save(raw, jobDir.resolve("raw_" + clean(raw.getOriginalFilename())));
        save(instructions, jobDir.resolve("instructions_" + clean(instructions.getOriginalFilename())));

        // Build multipart body for Python FastAPI (field names must match FastAPI params)
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("ideal", toPart("ideal", ideal));
        body.add("raw", toPart("raw", raw));
        body.add("instructions", toPart("instructions", instructions));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);

        HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);

        // Call FastAPI /process
        String aiProcessUrl = "http://localhost:8001/process";
        var aiResponse = restTemplate.postForEntity(aiProcessUrl, requestEntity, String.class);

        // Parse jobId from AI response
        JsonNode node = om.readTree(aiResponse.getBody());
        String aiJobId = node.get("jobId").asText();

        // Auto-finalize so downloads are ready
        String finalizeUrl = "http://localhost:8001/finalize/" + aiJobId;
        restTemplate.postForEntity(finalizeUrl, null, String.class);

        // Return ready download links (via Spring proxy)
        return ResponseEntity.ok(Map.of(
                "jobId", aiJobId,
                "idealUrl", "/api/download/" + aiJobId + "/ideal",
                "logUrl", "/api/download/" + aiJobId + "/log",
                "summaryUrl", "/api/download/" + aiJobId + "/summary"
        ));
    }

    /* ------------ helpers ------------ */

    private HttpEntity<ByteArrayResource> toPart(String fieldName, MultipartFile src) throws Exception {
        ByteArrayResource resource = new ByteArrayResource(src.getBytes()) {
            @Override public String getFilename() {
                String name = src.getOriginalFilename();
                return (name != null && !name.isBlank()) ? name : fieldName;
            }
        };
        HttpHeaders partHeaders = new HttpHeaders();
        partHeaders.setContentType(MediaType.parseMediaType(
                src.getContentType() != null ? src.getContentType() : "application/octet-stream"
        ));
        // IMPORTANT: use the actual field name, not "file"
        partHeaders.setContentDispositionFormData(fieldName, resource.getFilename());
        return new HttpEntity<>(resource, partHeaders);
    }

    private void save(MultipartFile f, Path to) throws Exception {
        Files.copy(f.getInputStream(), to, StandardCopyOption.REPLACE_EXISTING);
    }

    private String clean(String name) {
        if (name == null) return "file";
        return name.replaceAll("[^A-Za-z0-9._-]", "_");
    }
}