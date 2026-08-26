# dev-eks monitoring compatibility snapshot

> Canonical source: `k8s/overlays/dev-eks` and `k8s/base/monitoring`.
> This legacy directory is retained only for migration traceability.

중앙 Alloy는 Backend 로그를 읽지 않는다. Backend 로그는 Pod-local sidecar가
private Monitoring Loki로 전송하고, 이 DaemonSet은 Backend/KSM 메트릭만
private Monitoring Prometheus로 remote-write한다.

## Bastion에서 확인

```bash
aws eks update-kubeconfig --name kdt-travelplanner-dev-eks --region ap-northeast-2
aws s3 cp s3://<dev-eks-monitoring-bucket>/kubernetes/monitoring/ /tmp/travel-planner-monitoring --recursive
kubectl kustomize /tmp/travel-planner-monitoring
kubectl diff -k /tmp/travel-planner-monitoring
kubectl apply -k /tmp/travel-planner-monitoring
kubectl rollout status deployment/kube-state-metrics -n travel-planner-monitoring --timeout=180s
kubectl rollout status daemonset/alloy -n travel-planner-monitoring --timeout=180s
kubectl get pods -n travel-planner-monitoring -o wide
```

배포 전에는 `kubectl diff` 결과에서 namespace, ClusterRole/Binding, endpoint
ConfigMap, DaemonSet만 확인한다. 이 실행자는 Terraform apply나 `kubectl apply`를
수행하지 않는다.

## 백엔드 scrape 계약

backend Pod에는 다음 annotation과 bounded label을 추가한다. Pod IP를
하드코딩하지 않고 Alloy가 Kubernetes discovery 결과를 사용한다.

```yaml
metadata:
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9091"
    prometheus.io/path: /actuator/prometheus
  labels:
    app.kubernetes.io/name: travel-planner-backend
```

Alloy가 Prometheus remote-write를 `:9090/api/v1/write`로 전송한다.
environment/platform/job/namespace/pod/app 정도만 라벨로 남기며 동적
식별자와 URL은 라벨에 넣지 않는다.

## 이미지 provenance

- Grafana Alloy `v1.16.1`, Docker Hub multi-platform index digest 고정
- kube-state-metrics `v2.19.1`, Kubernetes 1.35 client-go(v0.35.4)와 호환되는 공식 태그 및
  registry.k8s.io index digest 고정
- Metrics Server `v0.8.1`(selected Kubernetes 1.35 compatibility), Cluster Autoscaler `v1.35.0`,
  AWS Load Balancer Controller `v3.3.0`(Kubernetes 1.22+)은 다음 플랫폼 단계에서
  동일한 tag+digest 계약으로 배포한다.

이미지 digest 또는 Kubernetes 버전을 바꾸려면 별도 검토된 변경으로 처리한다.
