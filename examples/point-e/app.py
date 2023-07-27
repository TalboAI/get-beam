"""
In this example, we’ll demonstrate using Beam to deploy a cloud endpoint 
for OpenAI’s Point-E, a state-of-the-art model for generating 3D objects.

You can run this script with the following shell command: 

beam run app.py:generate_mesh -d '{"prompt": "a bicycle"}
"""
from beam import App, Runtime, Image, Output, Volume

import torch
from tqdm.auto import tqdm

from point_e.diffusion.configs import DIFFUSION_CONFIGS, diffusion_from_config
from point_e.diffusion.sampler import PointCloudSampler
from point_e.models.download import load_checkpoint
from point_e.models.configs import MODEL_CONFIGS, model_from_config
from point_e.util.plotting import plot_point_cloud


# Define the environment
app = App(
    name="pointe",
    runtime=Runtime(
        cpu=8,
        memory="16Gi",
        gpu="T4",
        image=Image(
            python_packages=[
                "filelock",
                "Pillow",
                "torch",
                "fire",
                "humanize",
                "requests",
                "tqdm",
                "matplotlib",
                "scikit-image",
                "scipy",
                "numpy",
                "clip@git+https://github.com/openai/CLIP.git",
            ],
        ),
    ),
)


@app.run(outputs=[Output(path="mesh.ply")])
def generate_mesh(**inputs):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(device)
    print("creating base model...")
    base_name = "base40M-textvec"
    base_model = model_from_config(MODEL_CONFIGS[base_name], device)
    base_model.eval()
    base_diffusion = diffusion_from_config(DIFFUSION_CONFIGS[base_name])

    print("creating upsample model...")
    upsampler_model = model_from_config(MODEL_CONFIGS["upsample"], device)
    upsampler_model.eval()
    upsampler_diffusion = diffusion_from_config(DIFFUSION_CONFIGS["upsample"])

    print("downloading base checkpoint...")
    base_model.load_state_dict(load_checkpoint(base_name, device))

    print("downloading upsampler checkpoint...")
    upsampler_model.load_state_dict(load_checkpoint("upsample", device))

    sampler = PointCloudSampler(
        device=device,
        models=[base_model, upsampler_model],
        diffusions=[base_diffusion, upsampler_diffusion],
        num_points=[1024, 4096 - 1024],
        aux_channels=["R", "G", "B"],
        guidance_scale=[3.0, 0.0],
        model_kwargs_key_filter=("texts", ""),  # Do not condition the upsampler at all
    )

    prompt = inputs["prompt"]
    print(f"generating image for prompt: {prompt}")

    # Produce a sample from the model.
    samples = None
    for x in tqdm(
        sampler.sample_batch_progressive(
            batch_size=1, model_kwargs=dict(texts=[prompt])
        )
    ):
        samples = x

    pc = sampler.output_to_point_clouds(samples)[0]
    with open("mesh.ply", "wb") as f:
        pc.write_ply(f)
        print(pc)

    print("mesh generated")
