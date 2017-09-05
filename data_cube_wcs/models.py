from django.db import models

from .utils import data_access_api


class CoverageOffering(models.Model):
    """Contains all information required for formatting coverage offering xml responses"""

    description = models.CharField(max_length=250)
    name = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=100)
    min_latitude = models.FloatField()
    max_latitude = models.FloatField()
    min_longitude = models.FloatField()
    max_longitude = models.FloatField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    def get_min_point(self):
        """Get a lon lat point as per the gml:pos requirement"""
        return "{} {}".format(self.min_longitude, self.min_latitude)

    def get_max_point(self):
        """Get a lon lat point as per the gml:pos requirement"""
        return "{} {}".format(self.max_longitude, self.max_latitude)

    def get_start_time(self):
        """Get a iso8601 formatted datetime"""
        return self.start_time.isoformat()

    def get_end_time(self):
        """Get a iso8601 formatted datetime"""
        return self.end_time.isoformat()

    def get_temporal_domain(self, iso8601=True):
        """The temporal domain is specified as one or more iso8601 datetimes"""
        return CoverageTemporalDomainEntry.objects.filter(coverage_offering=self).order_by('date')

    def get_rangeset(self):
        """Get the set of rangeset entries that match this coverage"""
        return CoverageRangesetEntry.objects.filter(coverage_offering=self).order_by('pk')

    def get_measurements(self):
        with data_access_api.DataAccessApi() as dc:
            return dc.dc.list_measurements().ix[self.name].index.values

    def get_nodata_values(self):
        with data_access_api.DataAccessApi() as dc:
            return dc.dc.list_measurements().ix[self.name]['nodata'].values

    @classmethod
    def update_or_create_coverages(cls, update_aux=False):
        """Uses the Data Cube data access api to update database representations of coverages"""

        with data_access_api.DataAccessApi() as dc:
            product_details = dc.dc.list_products()[dc.dc.list_products()['format'] == "NetCDF"]
            product_details['label'] = product_details.apply(
                lambda row: "{} - {}".format(row['platform'], row['name']), axis=1)

            extent_data = {product: dc.get_datacube_metadata(product) for product in product_details['name'].values}

            product_details['min_latitude'] = product_details.apply(
                lambda row: extent_data[row['name']]['lat_extents'][0], axis=1)
            product_details['max_latitude'] = product_details.apply(
                lambda row: extent_data[row['name']]['lat_extents'][1], axis=1)
            product_details['min_longitude'] = product_details.apply(
                lambda row: extent_data[row['name']]['lon_extents'][0], axis=1)
            product_details['max_longitude'] = product_details.apply(
                lambda row: extent_data[row['name']]['lon_extents'][1], axis=1)
            product_details['start_time'] = product_details.apply(
                lambda row: extent_data[row['name']]['time_extents'][0], axis=1)
            product_details['end_time'] = product_details.apply(
                lambda row: extent_data[row['name']]['time_extents'][1], axis=1)

            list_of_dicts = product_details[[
                'name', 'description', 'label', 'min_latitude', 'max_latitude', 'min_longitude', 'max_longitude',
                'start_time', 'end_time'
            ]].to_dict('records')

            for model in list_of_dicts:
                obj, created = cls.objects.update_or_create(**model)

        if update_aux:
            cls.create_rangeset()
            cls.create_temporal_domain()

    @classmethod
    def create_temporal_domain(cls):

        def get_acquisition_dates(coverage):
            with data_access_api.DataAccessApi() as dc:
                return dc.list_acquisition_dates(coverage.name)

        for coverage in cls.objects.all():
            temporal_domain = [
                CoverageTemporalDomain(coverage_offering=coverage, date=date)
                for date in get_acquisition_dates(coverage)
                if not CoverageTemporalDomain.objects.filter(coverage_offering=coverage, date=date).exists()
            ]

            CoverageTemporalDomain.objects.bulk_create(temporal_domain)

    @classmethod
    def create_rangeset(cls):
        with data_access_api.DataAccessApi() as dc:
            for coverage in cls.objects.all():
                bands = dc.dc.list_measurements().ix[coverage.name]
                nodata_values = bands['nodata'].values
                band_names = bands.index.values

                rangeset = [
                    CoverageRangeset(coverage_offering=coverage, band_name=band_name, null_value=nodata_value)
                    for band_name, nodata_value in zip(band_names, nodata_values)
                    if not CoverageRangeset.objects.filter(
                        coverage_offering=coverage, band_name=band_name, null_value=nodata_value).exists()
                ]

                CoverageRangeset.objects.bulk_create(rangeset)


class CoverageTemporalDomainEntry(models.Model):
    """Holds the temporal domain of given coverages so they don't need to be fetched by the DC API each call"""

    coverage_offering = models.ForeignKey(CoverageOffering, on_delete=models.CASCADE)
    date = models.DateTimeField()

    class Meta:
        unique_together = (('coverage_offering', 'date'))

    def get_timestring(self):
        return self.date.isoformat()


class CoverageRangesetEntry(models.Model):
    """Holds the band name/null value combination needed for a RangeSet Element"""

    coverage_offering = models.ForeignKey(CoverageOffering, on_delete=models.CASCADE)
    band_name = models.CharField(max_length=50)
    null_value = models.CharField(max_length=50)
