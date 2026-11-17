import os
from typing import Dict, Any, Optional, List
from PIL import Image, ExifTags

class GeoExifService:
    """
    Automated Geotagging & IPTC Metadata Injection Engine.
    Embeds physical coordinates of RAIS Agencies Sundupalli Road Depot (14.059359 N, 78.759402 E)
    directly into depot and product photos before publishing to Google Maps or web catalogs.
    Google Vision AI extracts embedded EXIF GPS tags to anchor business proximity.
    """

    LATITUDE = 14.059359
    LONGITUDE = 78.759402
    BUSINESS_NAME = "RAIS Agencies"
    ADDRESS = "Beside Indel Money Bank, Sundupalli Road, Near Reddies Colony, Rayachoty – 516269"

    def _dec_to_dms(self, deg_float: float):
        """Converts decimal degrees to (degrees, minutes, seconds) tuple for EXIF GPS."""
        d = int(deg_float)
        m = int((deg_float - d) * 60)
        s = round((deg_float - d - m/60.0) * 3600.0, 4)
        return (d, m, s)

    def geotag_image(self, input_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """Injects verified GPS EXIF metadata into a JPEG/TIFF image."""
        if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
            return {"status": "SKIPPED", "message": f"File {input_path} is empty or missing"}

        out = output_path or input_path

        try:
            with Image.open(input_path) as img:
                exif = img.getexif()

                # IFD code for GPSInfo is 0x8825 (34853)
                gps_ifd = exif.get_ifd(0x8825)
                gps_ifd[1] = 'N'  # GPSLatitudeRef
                gps_ifd[2] = self._dec_to_dms(self.LATITUDE)  # GPSLatitude
                gps_ifd[3] = 'E'  # GPSLongitudeRef
                gps_ifd[4] = self._dec_to_dms(self.LONGITUDE)  # GPSLongitude

                # Tag 270 (0x010e) is ImageDescription, 315 (0x013b) is Artist
                exif[0x010e] = f"{self.BUSINESS_NAME} Wholesale Cold-Chain Depot, Sundupalli Road, Rayachoty"
                exif[0x013b] = self.BUSINESS_NAME

                img.save(out, exif=exif)

            return {
                "status": "SUCCESS",
                "file": out,
                "latitude": self.LATITUDE,
                "longitude": self.LONGITUDE,
                "business": self.BUSINESS_NAME,
                "address": self.ADDRESS
            }
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    def batch_geotag_directory(self, dir_path: str) -> List[Dict[str, Any]]:
        """Batch geotags all images in a given directory."""
        results = []
        if not os.path.exists(dir_path):
            return results

        for fname in os.listdir(dir_path):
            if fname.lower().endswith(('.jpg', '.jpeg')):
                fpath = os.path.join(dir_path, fname)
                results.append(self.geotag_image(fpath))
        return results

geo_exif_service = GeoExifService()
