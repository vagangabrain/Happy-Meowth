import onnxruntime as ort
import numpy as np
import aiohttp
from PIL import Image
import io
import os
import json
import time
import hashlib
from typing import Optional, Tuple

SUBMODULE_PATH = os.path.dirname(os.path.realpath(__file__))  
ONNX_PATH = os.path.join(SUBMODULE_PATH, "model/pokemon_cnn_v2.onnx")
LABELS_PATH = os.path.join(SUBMODULE_PATH, "model/labels_v2.json")
SAVE_PATH = os.path.join(SUBMODULE_PATH, "data/commands/pokemon/images")

class PredictionCache:
    """Simple in-memory cache for predictions"""
    def __init__(self, max_size=1000, ttl_seconds=3600):  # 1 hour TTL
        self.cache = {}
        self.timestamps = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def _cleanup_expired(self):
        """Remove expired entries"""
        current_time = time.time()
        expired_keys = [
            key for key, timestamp in self.timestamps.items()
            if current_time - timestamp > self.ttl_seconds
        ]
        for key in expired_keys:
            self.cache.pop(key, None)
            self.timestamps.pop(key, None)

    def get(self, key: str) -> Optional[Tuple[str, str]]:
        """Get cached prediction if valid"""
        self._cleanup_expired()
        if key in self.cache:
            current_time = time.time()
            if current_time - self.timestamps[key] <= self.ttl_seconds:
                return self.cache[key]
            else:
                # Remove expired entry
                self.cache.pop(key, None)
                self.timestamps.pop(key, None)
        return None

    def set(self, key: str, value: Tuple[str, str]):
        """Cache a prediction"""
        self._cleanup_expired()

        # Remove oldest entries if cache is full
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.timestamps.keys(), key=lambda k: self.timestamps[k])
            self.cache.pop(oldest_key, None)
            self.timestamps.pop(oldest_key, None)

        self.cache[key] = value
        self.timestamps[key] = time.time()

class Prediction:
    def __init__(self, onnx_path=ONNX_PATH, labels_path=LABELS_PATH, save_path=SAVE_PATH):
        self.onnx_path = onnx_path
        self.labels_path = labels_path
        self.save_path = save_path
        self.class_names = self.load_class_names()
        self.cache = PredictionCache()

        # Enhanced ONNX session setup with performance optimizations
        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = min(4, os.cpu_count())  # Limit threads for Railway
        sess_opts.inter_op_num_threads = 1
        sess_opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        # Use only CPU provider for Railway free tier
        providers = ["CPUExecutionProvider"]

        self.ort_session = ort.InferenceSession(
            self.onnx_path, 
            sess_options=sess_opts, 
            providers=providers
        )

        print(f"ONNX session initialized with providers: {self.ort_session.get_providers()}")

    def generate_labels_file_from_save_path(self):
        if not os.path.exists(self.save_path):
            raise FileNotFoundError(f"SAVE_PATH does not exist: {self.save_path}")

        class_names = sorted([
            d for d in os.listdir(self.save_path)
            if os.path.isdir(os.path.join(self.save_path, d))
        ])

        os.makedirs(os.path.dirname(self.labels_path), exist_ok=True)
        with open(self.labels_path, "w", encoding="utf-8") as f:
            json.dump(class_names, f, indent=2)

        return class_names

    def load_class_names(self):
        if not os.path.exists(self.labels_path):
            return self.generate_labels_file_from_save_path()

        with open(self.labels_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                # Sort by numeric keys and extract Pokemon names
                sorted_keys = sorted(data.keys(), key=lambda x: int(x))
                return [data[k].strip('"') for k in sorted_keys]  # Remove quotes if present
            if isinstance(data, list):
                return [name.strip('"') for name in data]  # Remove quotes if present
            raise ValueError("labels_v2.json must be a list or dict")

    def _generate_cache_key(self, url: str) -> str:
        """Generate cache key from URL"""
        return hashlib.md5(url.encode()).hexdigest()

    async def preprocess_image_from_url(self, url: str, session: aiohttp.ClientSession):
        """Async image preprocessing with optimized settings"""
        try:
            # Use the shared HTTP session from main module
            timeout = aiohttp.ClientTimeout(total=5, connect=2)
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status} error fetching image")

                image_data = await response.read()

        except Exception as e:
            raise ValueError(f"Failed to load image from URL: {e}")

        try:
            # Process image
            image = Image.open(io.BytesIO(image_data)).convert("RGB")
        except Exception as e:
            raise ValueError(f"Failed to process image: {e}")

        # Resize with high quality resampling
        image = image.resize((224, 224), Image.LANCZOS)

        # Convert to numpy array and normalize
        image = np.array(image, dtype=np.float32) / 255.0

        # ImageNet normalization
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        image = (image - mean) / std

        # Convert to CHW format and add batch dimension
        image = np.transpose(image, (2, 0, 1))  # CHW
        image = np.expand_dims(image, axis=0).astype(np.float32)  # NCHW

        return image

    def softmax(self, x):
        """Vectorized softmax computation"""
        exp_x = np.exp(x - np.max(x))
        return exp_x / np.sum(exp_x)

    async def predict(self, url: str, session: aiohttp.ClientSession = None) -> Tuple[str, str]:
        """Async prediction with caching"""
        # Check cache first
        cache_key = self._generate_cache_key(url)
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return cached_result

        # Get HTTP session from main module if not provided
        if session is None:
            import __main__
            session = getattr(__main__, 'http_session', None)
            if session is None:
                raise ValueError("HTTP session not available")

        # Preprocess image
        image = await self.preprocess_image_from_url(url, session)

        # Run inference
        inputs = {self.ort_session.get_inputs()[0].name: image}
        outputs = self.ort_session.run(None, inputs)
        logits = outputs[0][0]

        # Get prediction
        pred_idx = int(np.argmax(logits))
        probabilities = self.softmax(logits)
        prob = float(probabilities[pred_idx])

        name = self.class_names[pred_idx] if pred_idx < len(self.class_names) else f"unknown_{pred_idx}"
        confidence = f"{prob * 100:.2f}%"

        # Cache result
        result = (name, confidence)
        self.cache.set(cache_key, result)

        return result

    def predict_sync(self, url: str) -> Tuple[str, str]:
        """Synchronous prediction for backwards compatibility"""
        import requests

        # Check cache first
        cache_key = self._generate_cache_key(url)
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return cached_result

        try:
            response = requests.get(url, timeout=5)
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
        except Exception as e:
            raise ValueError(f"Failed to load image from URL: {e}")

        # Resize with high quality resampling
        image = image.resize((224, 224), Image.LANCZOS)

        # Convert to numpy array and normalize
        image = np.array(image, dtype=np.float32) / 255.0

        # ImageNet normalization
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        image = (image - mean) / std

        # Convert to CHW format and add batch dimension
        image = np.transpose(image, (2, 0, 1))
        image = np.expand_dims(image, axis=0).astype(np.float32)

        # Run inference
        inputs = {self.ort_session.get_inputs()[0].name: image}
        outputs = self.ort_session.run(None, inputs)
        logits = outputs[0][0]

        pred_idx = int(np.argmax(logits))
        probabilities = self.softmax(logits)
        prob = float(probabilities[pred_idx])

        name = self.class_names[pred_idx] if pred_idx < len(self.class_names) else f"unknown_{pred_idx}"
        confidence = f"{prob * 100:.2f}%"

        # Cache result
        result = (name, confidence)
        self.cache.set(cache_key, result)

        return result

def main():
    """Test function for development"""
    import asyncio
    import aiohttp

    async def test_predict():
        predictor = Prediction()

        async with aiohttp.ClientSession() as session:
            while True:
                url = input("Enter Pokémon image URL (or 'q' to quit): ").strip()
                if url.lower() == 'q':
                    break

                try:
                    name, confidence = await predictor.predict(url, session)
                    print(f"Predicted Pokémon: {name} (confidence: {confidence})")
                except Exception as e:
                    print(f"Error: {e}")

    asyncio.run(test_predict())

if __name__ == "__main__":
    main()
