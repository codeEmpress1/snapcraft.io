export default function formatImageChanges(
  bannerUrls: string[],
  iconUrl: string,
  screenshotUrls: string[],
  screenshots: FileList[],
) {
  const images = [];

  if (bannerUrls.length > 0) {
    images.push({
      url: bannerUrls[0],
      type: "banner",
      status: "uploaded",
    });
  }

  if (iconUrl) {
    images.push({
      url: iconUrl,
      type: "icon",
      status: "uploaded",
    });
  }

  if (screenshotUrls.length) {
    screenshotUrls.forEach((url) => {
      images.push({
        url,
        type: "screenshot",
        status: "uploaded",
      });
    });
  }

  if (screenshots) {
    screenshots.forEach((screenshot) => {
      if (screenshot[0]) {
        images.push({
          url: URL.createObjectURL(screenshot[0]),
          type: "screenshot",
          status: "new",
          name: screenshot[0].name,
        });
      }
    });
  }

  return images;
}
