# Reference files

The default container configuration expects:

```text
references/
├── mm10/gencode.vM25.annotation.gtf
└── hg38/gencode.v44.annotation.gtf
```

The directory is mounted read-only at `/refs` by `compose.yaml`.

To use different versions or paths, copy `config/references.example.json`, edit it, mount it into the container, and set `ASTK_REFERENCE_CONFIG`.
