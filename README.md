# ASR Server on AWS EKS

This repository contains all necessary files and instructions to deploy an Automatic Speech Recognition (ASR) server on AWS Elastic Kubernetes Service (EKS) with GPU sharing, autoscaling, and monitoring capabilities.

---

## 📦 Prerequisites

Make sure to install the following tools:

- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [eksctl](https://eksctl.io/installation/)
- [helm](https://helm.sh/docs/intro/install/)

---

## 🔐 IAM Policy Setup

Ensure the following policies are attached to your IAM user:

- `AmazonEBSCSIDriverPolicy`
- `AmazonEKS_CNI_Policy`
- `AmazonEKSBlockStoragePolicy`
- `AmazonEKSClusterPolicy`
- `AmazonEKSComputePolicy`
- `AmazonEKSFargatePodExecutionRolePolicy`
- `AmazonEKSLoadBalancingPolicy`
- `AmazonEKSLocalOutpostClusterPolicy`
- `AmazonEKSNetworkingPolicy`
- `AmazonEKSServicePolicy`
- `AmazonEKSVPCResourceController`
- `AmazonEKSWorkerNodeMinimalPolicy`
- `AmazonEKSWorkerNodePolicy`
- `AmazonSSMManagedInstanceCore`
- `AutoScalingFullAccess`
- `AWSFaultInjectionSimulatorEKSAccess`

---

## 📁 Project Structure

| File/Folder             | Description |
|-------------------------|-------------|
| `asr.py`                | ASR model class. Modify this file to use your own ASR model. Implement `predict(self, messages)` method. |
| `asr_server.py`         | FastAPI application endpoint, manages request queue and client pool. |
| `audios/`               | Sample audios for testing. |
| `client_logs/`          | Logging for client call results. |
| `client.py`             | Simple script for testing ASR service. |
| `client.sh`             | Bash script for simulating multiple client calls. |
| `config.py`             | Configuration for the ASR server and clients. |
| `cluster.yaml`          | Defines EKS cluster parameters. |
| `deployment.yaml`       | ASR pod deployment configuration. |
| `Dockerfile`            | For building the ASR Docker image. |
| `requirements.txt`      | Python dependencies for Docker image. |
| `ebs-csi-policy.json`   | EBS CSI driver policy. |
| `gp2-immediate.yaml`    | Custom persistent volume configuration. |
| `hpa.yaml`              | KEDA-based HPA configuration. |
| `iam_policy.json`       | IAM policy for load balancing. |
| `ingress.yaml`          | ALB Ingress configuration. |
| `pvc.yaml`              | Persistent Volume Claim configuration. |
| `service-monitor.yaml`  | Prometheus service monitor config. |
| `service.yaml`          | ASR service definition. |
| `time-slicing-config-all.yaml` | NVIDIA GPU time-sharing config. |

---

## 🛠 Cluster Setup

### Define Environment Variables

```
CLUSTER_NAME="asr-cluster"
REGION="eu-west-1"
VPC_ID="YOUR_VPC"
ACCOUNT_ID="YOUR_ACCOUNT_ID"
POLICY_NAME="AWSLoadBalancerControllerIAMPolicy"
SA_NAME="aws-load-balancer-controller"
```

## 🛠 Create the EKS Cluster
Edit and adjust parameters in cluster.yaml as needed.
```
eksctl create cluster -f cluster.yaml
aws eks --region $REGION update-kubeconfig --name $CLUSTER_NAME
```

## 🚀 Install AWS Load Balancer Controller
```
helm repo add eks https://aws.github.io/eks-charts
helm repo update

curl -o iam_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json

aws iam create-policy \
  --policy-name $POLICY_NAME \
  --policy-document file://iam_policy.json

eksctl utils associate-iam-oidc-provider --region $REGION --cluster $CLUSTER_NAME --approve

eksctl create iamserviceaccount \
  --cluster $CLUSTER_NAME \
  --namespace kube-system \
  --name $SA_NAME \
  --attach-policy-arn arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_NAME \
  --approve

helm install $SA_NAME eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=$CLUSTER_NAME \
  --set serviceAccount.create=false \
  --set serviceAccount.name=$SA_NAME \
  --set region=$REGION \
  --set vpcId=$VPC_ID

```

## 🔊 ASR Server Implementation
```
Already implemented, files to modify if needed:
 - asr_server.py
 - asr.py
 - config.py
 - client.py
 - client.sh
```

## 🐳 Build & Push Docker Image
Change to your docker_repo if needed. If you want to use my already built Docker image, you can skip this step
```
DOCKER_REPO="mailong25/asr-server"
docker build -t $DOCKER_REPO .
docker push $DOCKER_REPO
```

## 📦 Deploy ASR Application
Edit deployment.yaml, service.yaml, and ingress.yaml if needed.
```
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml
kubectl get pods -A
```

## 🧪 Test ASR Service
- Locate Load Balancer DNS from AWS Console.
- Update SERVER_URI in config.py.
- Run:
```
python client.py
```

## Now the autoscaling part

## ⚙️ GPU Time Sharing with NVIDIA Plugin
```
kubectl create -n kube-system -f time-slicing-config-all.yaml

helm repo add nvdp https://nvidia.github.io/k8s-device-plugin
helm repo update

helm upgrade -i nvdp nvdp/nvidia-device-plugin \
    --version=0.14.1 \
    --namespace kube-system \
    --create-namespace \
    --set config.name=time-slicing-config-all

kubectl scale deployment asr-deployment --replicas=2
kubectl get pods -A

```

## 📈 Set Up Prometheus for Monitoring
```
eksctl utils associate-iam-oidc-provider --region=$REGION --cluster=$CLUSTER_NAME --approve

eksctl create iamserviceaccount \
  --region $REGION \
  --name ebs-csi-controller-sa \
  --namespace kube-system \
  --cluster $CLUSTER_NAME \
  --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy \
  --approve \
  --role-only \
  --role-name AmazonEKS_EBS_CSI_DriverRole

eksctl create addon --name aws-ebs-csi-driver --cluster $CLUSTER_NAME \
  --service-account-role-arn arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/AmazonEKS_EBS_CSI_DriverRole --force

kubectl apply -f gp2-immediate.yaml
kubectl apply -f pvc.yaml

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack

```

Create a ServiceMonitor:
```
kubectl apply -f service-monitor.yaml
kubectl port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090
```
For monitoring, in browser (http://localhost:9090), run this to check average response latency
```
avg(rate(response_latency_seconds_sum[2m]) / clamp_min(rate(response_latency_seconds_count[2m]), 1e-9))
```

## 📊 Horizontal Pod Autoscaling with KEDA using prometheus metric
```
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda
kubectl apply -f hpa.yaml
```
Now spawn multiple clients to test if the HPA work
```
sh client.sh 5 5
```

## 📈 Setup Cluster Autoscaler
```
aws iam create-policy \
  --policy-name AmazonEKSClusterAutoscalerPolicy \
  --policy-document file://<(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "autoscaling:DescribeAutoScalingGroups",
        "autoscaling:DescribeAutoScalingInstances",
        "autoscaling:DescribeLaunchConfigurations",
        "autoscaling:DescribeTags",
        "autoscaling:SetDesiredCapacity",
        "autoscaling:TerminateInstanceInAutoScalingGroup",
        "ec2:DescribeLaunchTemplateVersions"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)

eksctl utils associate-iam-oidc-provider --region=$REGION --cluster=$CLUSTER_NAME --approve

eksctl create iamserviceaccount \
  --cluster $CLUSTER_NAME \
  --namespace kube-system \
  --name cluster-autoscaler \
  --attach-policy-arn arn:aws:iam::$ACCOUNT_ID:policy/AmazonEKSClusterAutoscalerPolicy \
  --approve \
  --override-existing-serviceaccounts

helm repo add autoscaler https://kubernetes.github.io/autoscaler
helm repo update

helm upgrade --install cluster-autoscaler autoscaler/cluster-autoscaler \
  --namespace kube-system \
  --set autoDiscovery.clusterName=$CLUSTER_NAME \
  --set awsRegion=$REGION \
  --set rbac.serviceAccount.name=cluster-autoscaler \
  --set rbac.serviceAccount.create=false \
  --set fullnameOverride=cluster-autoscaler \
  --set extraArgs.balance-similar-node-groups=true \
  --set extraArgs.skip-nodes-with-system-pods=false \
  --set extraArgs.scale-down-enabled=true \
  --set extraArgs.scale-down-unneeded-time=2m \
  --set extraArgs.scale-down-delay-after-delete=2m \
  --set extraArgs.scale-down-delay-after-add=2m \
  --set extraArgs.max-node-provision-time=15m \
  --set extraArgs.scan-interval=1m

```

## 🔁 Run Load Test
This will spawn 40 clients to call the API
```
sh client.sh 40 30
```
Now use Prometheus to monitoring:
 - Total Requests per Minute:
```
sum(rate(response_latency_seconds_count[1m]))
```
 - Average Response Latency:
```
avg(rate(response_latency_seconds_sum[1m]) / clamp_min(rate(response_latency_seconds_count[1m]), 1e-9))
```
